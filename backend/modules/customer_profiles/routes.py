from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated, Literal
import uuid

from infrastructure.database import get_session
from modules.auth.dependencies import ActiveCurrentUserDep, CurrentUser
from modules.users.guards import require_user_permission
from modules.users.permissions import UserPermission
from .enums import KycStatusEnum
from .schemas import (
    CustomerProfileCreateSchema,
    CustomerProfileUpdateSchema,
    CustomerProfileResponseSchema,
    CustomerProfileSummarySchema,
    AdminCustomerProfileResponseSchema,
    KycRejectionSchema,
)
from .services import customer_profile_service

customer_profile_router = APIRouter()
admin_kyc_router = APIRouter()


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


# --- Admin KYC Review Routes ---

@admin_kyc_router.get(
    "",
    response_model=list[CustomerProfileSummarySchema],
    summary="List customer profiles for review"
)
async def list_profiles(
    current_user: Annotated[CurrentUser, Depends(require_user_permission(UserPermission.READ_KYC_PROFILES))],
    status: KycStatusEnum | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_session)
):
    return await customer_profile_service.list_profiles_for_review(
        db, kyc_status=status, limit=limit, offset=offset
    )


@admin_kyc_router.get(
    "/{profile_id}",
    response_model=AdminCustomerProfileResponseSchema,
    summary="Get full details of a profile for review"
)
async def get_profile_detail(
    profile_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_user_permission(UserPermission.READ_KYC_PROFILES))],
    db: AsyncSession = Depends(get_session)
):
    return await customer_profile_service.get_profile_by_id_for_admin(db, profile_id)


@admin_kyc_router.post(
    "/{profile_id}/start-review",
    response_model=AdminCustomerProfileResponseSchema,
    summary="Mark profile as under review"
)
async def start_profile_review(
    profile_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_user_permission(UserPermission.APPROVE_KYC_PROFILES))],
    db: AsyncSession = Depends(get_session)
):
    return await customer_profile_service.mark_under_review(db, profile_id, current_user.user_id)


@admin_kyc_router.post(
    "/{profile_id}/approve",
    response_model=AdminCustomerProfileResponseSchema,
    summary="Approve KYC profile"
)
async def approve_customer_profile(
    profile_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_user_permission(UserPermission.APPROVE_KYC_PROFILES))],
    db: AsyncSession = Depends(get_session)
):
    return await customer_profile_service.approve_profile(db, profile_id, current_user.user_id)


@admin_kyc_router.post(
    "/{profile_id}/reject",
    response_model=AdminCustomerProfileResponseSchema,
    summary="Reject KYC profile"
)
async def reject_customer_profile(
    profile_id: uuid.UUID,
    payload: KycRejectionSchema,
    current_user: Annotated[CurrentUser, Depends(require_user_permission(UserPermission.APPROVE_KYC_PROFILES))],
    db: AsyncSession = Depends(get_session)
):
    return await customer_profile_service.reject_profile(
        db, profile_id, current_user.user_id, payload.rejection_reason
    )
