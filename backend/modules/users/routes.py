import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database import get_session
from modules.auth.dependencies import ActiveCurrentUserDep, CurrentUser
from .models import User
from .schemas import (
    UserReadSchema,
    StaffUserCreateSchema,
    AdminUserUpdateSchema,
    UserRoleUpdateSchema,
    RoleChoicesSchema,
    AccountStatusSchema,
)
from .services import user_service
from .guards import require_user_permission
from .permissions import UserPermission


users_router = APIRouter()
admin_router = APIRouter()


# ==========================================
# Regular User Routes
# ==========================================

@users_router.get("/me", response_model=UserReadSchema)
async def get_me(
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session)
):
    user = await user_service.get_by_id(db, current_user.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user


# ==========================================
# Administrative User Management Routes
# ==========================================

@admin_router.get("", response_model=list[UserReadSchema])
async def list_users(
    current_user: Annotated[CurrentUser, Depends(require_user_permission(UserPermission.READ_USERS))],
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_session)
):
    return await user_service.list_users(db, skip, limit)


@admin_router.get("/{user_id}", response_model=UserReadSchema)
async def get_user_detail(
    user_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_user_permission(UserPermission.READ_USER_DETAIL))],
    db: AsyncSession = Depends(get_session)
):
    user = await user_service.get_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    user_service.ensure_actor_can_manage_target(current_user, user)
    return user


@admin_router.post("/staff", response_model=UserReadSchema)
async def create_staff(
    payload: StaffUserCreateSchema,
    current_user: Annotated[CurrentUser, Depends(require_user_permission(UserPermission.CREATE_STAFF_USERS))],
    db: AsyncSession = Depends(get_session)
):
    user_service.ensure_actor_can_create_staff_role(current_user, payload.role)
    
    # Check duplicate email
    existing_email = await user_service.get_by_email(db, payload.email)
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Check duplicate username
    if payload.username:
        existing_username = await db.execute(select(User).where(User.username == payload.username))
        if existing_username.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already registered"
            )
            
    # Check duplicate identification number
    existing_id = await db.execute(select(User).where(User.id_no == payload.id_no))
    if existing_id.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Identification number already registered"
        )
        
    from modules.auth.services import auth_service
    hashed_password = auth_service.get_password_hash(payload.password)
    return await user_service.create_staff_user(db, payload, hashed_password)


@admin_router.patch("/{user_id}", response_model=UserReadSchema)
async def update_user(
    user_id: uuid.UUID,
    payload: AdminUserUpdateSchema,
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session)
):
    user = await user_service.get_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
        
    user_service.ensure_actor_is_not_target(current_user, user_id)
    user_service.ensure_actor_can_manage_target(current_user, user)
    
    # Validate context-aware permission
    required_permission = (
        UserPermission.UPDATE_CUSTOMER_PROFILE
        if user.role == RoleChoicesSchema.CUSTOMER
        else UserPermission.UPDATE_USER_ADMIN_FIELDS
    )
    from .permissions import can_user
    if not can_user(current_user.platform_role, required_permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden"
        )
        
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.id_no is not None:
        existing_id = await db.execute(select(User).where(User.id_no == payload.id_no, User.id != user_id))
        if existing_id.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Identification number already registered"
            )
        user.id_no = payload.id_no
        
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@admin_router.patch("/{user_id}/role", response_model=UserReadSchema)
async def change_role(
    user_id: uuid.UUID,
    payload: UserRoleUpdateSchema,
    current_user: Annotated[CurrentUser, Depends(require_user_permission(UserPermission.CHANGE_USER_ROLE))],
    db: AsyncSession = Depends(get_session)
):
    user = await user_service.get_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
        
    user_service.ensure_actor_is_not_target(current_user, user_id)
    user_service.ensure_actor_can_manage_target(current_user, user)
    user_service.ensure_actor_can_assign_role(current_user, payload.role)
    
    user.role = payload.role
    user.is_superuser = (payload.role == RoleChoicesSchema.SUPER_ADMIN)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@admin_router.post("/{user_id}/lock", response_model=UserReadSchema)
async def lock_user(
    user_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_user_permission(UserPermission.LOCK_USERS))],
    db: AsyncSession = Depends(get_session)
):
    user = await user_service.get_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
        
    user_service.ensure_actor_is_not_target(current_user, user_id)
    user_service.ensure_actor_can_manage_target(current_user, user)
    
    user.account_status = AccountStatusSchema.LOCKED
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@admin_router.post("/{user_id}/unlock", response_model=UserReadSchema)
async def unlock_user(
    user_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_user_permission(UserPermission.UNLOCK_USERS))],
    db: AsyncSession = Depends(get_session)
):
    user = await user_service.get_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
        
    user_service.ensure_actor_is_not_target(current_user, user_id)
    user_service.ensure_actor_can_manage_target(current_user, user)
    
    user.account_status = AccountStatusSchema.ACTIVE
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@admin_router.post("/{user_id}/activate", response_model=UserReadSchema)
async def activate_user(
    user_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_user_permission(UserPermission.ACTIVATE_USERS))],
    db: AsyncSession = Depends(get_session)
):
    user = await user_service.get_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
        
    user_service.ensure_actor_is_not_target(current_user, user_id)
    user_service.ensure_actor_can_manage_target(current_user, user)
    
    user.is_active = True
    user.account_status = AccountStatusSchema.ACTIVE
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@admin_router.post("/{user_id}/deactivate", response_model=UserReadSchema)
async def deactivate_user(
    user_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_user_permission(UserPermission.ACTIVATE_USERS))],
    db: AsyncSession = Depends(get_session)
):
    user = await user_service.get_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
        
    user_service.ensure_actor_is_not_target(current_user, user_id)
    user_service.ensure_actor_can_manage_target(current_user, user)
    
    user.is_active = False
    user.account_status = AccountStatusSchema.INACTIVE
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@admin_router.delete("/{user_id}")
async def delete_user(
    user_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_user_permission(UserPermission.DELETE_USERS))],
    db: AsyncSession = Depends(get_session)
):
    user = await user_service.get_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
        
    user_service.ensure_actor_is_not_target(current_user, user_id)
    user_service.ensure_actor_can_manage_target(current_user, user)
    
    await db.delete(user)
    await db.commit()
    return {"message": "User deleted successfully"}
