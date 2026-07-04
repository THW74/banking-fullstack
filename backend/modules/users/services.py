import uuid
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from .models import User
from fastapi import HTTPException, status
from modules.users.schemas import (
    UserCreateSchema,
    AccountStatusSchema,
    RoleChoicesSchema,
    StaffUserCreateSchema,
    SecurityQuestionsSchema,
)
from modules.auth.dependencies import CurrentUser


class UserService:
    async def get_by_email(self, db: AsyncSession, email: str) -> User | None:
        statement = select(User).where(User.email == email)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_id(self, db: AsyncSession, user_id: uuid.UUID) -> User | None:
        statement = select(User).where(User.id == user_id)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def create_user(
        self,
        db: AsyncSession,
        user_in: UserCreateSchema,
        hashed_password: str,
        security_answer_hash: str,
    ) -> User:
        db_user = User(
            username=user_in.username,
            email=user_in.email,
            full_name=user_in.full_name,
            id_no=user_in.id_no,
            security_question=user_in.security_question,
            security_answer_hash=security_answer_hash,
            hashed_password=hashed_password,
            is_active=False,
            is_superuser=False,
            account_status=AccountStatusSchema.INACTIVE,
            role=RoleChoicesSchema.CUSTOMER,
        )
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user

    async def create_staff_user(
        self,
        db: AsyncSession,
        user_in: StaffUserCreateSchema,
        hashed_password: str,
    ) -> User:
        db_user = User(
            username=user_in.username,
            email=user_in.email,
            full_name=user_in.full_name,
            id_no=user_in.id_no,
            security_question=SecurityQuestionsSchema.FAVORITE_COLOR,  # Default placeholder for staff
            security_answer_hash="",  # Unused for staff registered by admin
            hashed_password=hashed_password,
            is_active=True,
            is_superuser=(user_in.role == RoleChoicesSchema.SUPER_ADMIN),
            account_status=AccountStatusSchema.ACTIVE,
            role=user_in.role,
        )
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user

    async def list_users(self, db: AsyncSession, skip: int = 0, limit: int = 100) -> list[User]:
        statement = select(User).offset(skip).limit(limit)
        result = await db.execute(statement)
        return result.scalars().all()

    def ensure_actor_is_not_target(self, actor: CurrentUser, target_id: uuid.UUID) -> None:
        if actor.user_id == target_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot perform this action on your own account"
            )

    def ensure_actor_can_manage_target(self, actor: CurrentUser, target: User) -> None:
        if actor.platform_role == RoleChoicesSchema.SUPER_ADMIN:
            return
        if target.role in {RoleChoicesSchema.ADMIN, RoleChoicesSchema.SUPER_ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot manage admin users"
            )
        if actor.platform_role == RoleChoicesSchema.BRANCH_MANAGER:
            # Branch Manager can lock/activate CUSTOMER only
            if target.role != RoleChoicesSchema.CUSTOMER:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Forbidden"
                )

    def ensure_actor_can_assign_role(self, actor: CurrentUser, requested_role: RoleChoicesSchema) -> None:
        if actor.platform_role != RoleChoicesSchema.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only super admin can change roles"
            )

    def ensure_actor_can_create_staff_role(self, actor: CurrentUser, target_role: RoleChoicesSchema) -> None:
        if actor.platform_role == RoleChoicesSchema.SUPER_ADMIN:
            if target_role == RoleChoicesSchema.SUPER_ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot create super admin"
                )
            return
        if actor.platform_role == RoleChoicesSchema.ADMIN:
            if target_role not in {
                RoleChoicesSchema.BRANCH_MANAGER,
                RoleChoicesSchema.ACCOUNT_EXECUTIVE,
                RoleChoicesSchema.TELLER,
            }:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Admin cannot create admin or super admin"
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden"
            )


user_service = UserService()

