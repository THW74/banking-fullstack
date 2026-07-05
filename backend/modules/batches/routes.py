import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database import get_session
from modules.auth.dependencies import CurrentUser
from modules.users.guards import require_user_permission
from modules.users.permissions import UserPermission
from modules.accounts.enums import AccountCurrencyEnum
from .enums import (
    EndOfDayBatchStatusEnum,
    EndOfDayValidationIssueSeverityEnum,
    EndOfDayValidationIssueTypeEnum,
)
from .schemas import EndOfDayBatchReadSchema, EndOfDayBatchRunSchema
from .services import end_of_day_batch_service

admin_batches_router = APIRouter()


@admin_batches_router.post(
    "/end-of-day",
    response_model=EndOfDayBatchReadSchema,
    status_code=status.HTTP_200_OK,
    summary="Run end-of-day audit close (Admin)",
)
async def run_end_of_day_batch(
    payload: EndOfDayBatchRunSchema,
    current_user: Annotated[
        CurrentUser,
        Depends(require_user_permission(UserPermission.RUN_END_OF_DAY_BATCHES)),
    ],
    db: AsyncSession = Depends(get_session),
):
    return await end_of_day_batch_service.run_end_of_day_batch(
        db,
        payload.business_date,
        current_user.user_id,
        payload.run_notes,
        payload.check_daily_snapshots,
    )


@admin_batches_router.get(
    "/end-of-day",
    response_model=list[EndOfDayBatchReadSchema],
    summary="List end-of-day audit closes (Staff/Admin)",
)
async def list_end_of_day_batches(
    current_user: Annotated[
        CurrentUser,
        Depends(require_user_permission(UserPermission.READ_END_OF_DAY_BATCHES)),
    ],
    business_date: date | None = Query(default=None),
    status_filter: EndOfDayBatchStatusEnum | None = Query(
        default=None, alias="status"
    ),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    is_balanced: bool | None = Query(default=None),
    has_validation_issues: bool | None = Query(default=None),
    requested_by_user_id: uuid.UUID | None = Query(default=None),
    currency: AccountCurrencyEnum | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
):
    return await end_of_day_batch_service.list_end_of_day_batches(
        db,
        business_date,
        status_filter,
        from_date,
        to_date,
        is_balanced,
        has_validation_issues,
        requested_by_user_id,
        currency,
        limit,
        offset,
    )


@admin_batches_router.get(
    "/end-of-day/{batch_id}",
    response_model=EndOfDayBatchReadSchema,
    summary="Get end-of-day audit close detail (Staff/Admin)",
)
async def get_end_of_day_batch(
    batch_id: uuid.UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_user_permission(UserPermission.READ_END_OF_DAY_BATCHES)),
    ],
    issue_type: EndOfDayValidationIssueTypeEnum | None = Query(default=None),
    issue_severity: EndOfDayValidationIssueSeverityEnum | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
):
    return await end_of_day_batch_service.get_end_of_day_batch(
        db, batch_id, issue_type, issue_severity
    )
