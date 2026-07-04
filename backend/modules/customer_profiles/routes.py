from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database import get_session
from modules.auth.dependencies import ActiveCurrentUserDep
from .schemas import (
    CustomerProfileCreateSchema,
    CustomerProfileUpdateSchema,
    CustomerProfileResponseSchema,
)
from .services import customer_profile_service

customer_profile_router = APIRouter()


@customer_profile_router.get(
    "",
    response_model=CustomerProfileResponseSchema,
    summary="Get own customer profile"
)
async def get_own_profile(
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session)
):
    profile = await customer_profile_service.get_by_user_id(db, current_user.user_id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found"
        )
    return profile


@customer_profile_router.post(
    "",
    response_model=CustomerProfileResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create initial profile draft"
)
async def create_profile_draft(
    payload: CustomerProfileCreateSchema,
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session)
):
    return await customer_profile_service.create_profile(db, current_user.user_id, payload)


@customer_profile_router.patch(
    "",
    response_model=CustomerProfileResponseSchema,
    summary="Update existing profile draft/rejected details"
)
async def update_profile_draft(
    payload: CustomerProfileUpdateSchema,
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session)
):
    return await customer_profile_service.update_profile(db, current_user.user_id, payload)


@customer_profile_router.post(
    "/submit",
    response_model=CustomerProfileResponseSchema,
    summary="Submit profile for review"
)
async def submit_profile_for_review(
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session)
):
    return await customer_profile_service.submit_profile(db, current_user.user_id)
