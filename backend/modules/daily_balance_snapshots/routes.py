import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database import get_session
from modules.accounts.enums import AccountCurrencyEnum
from modules.auth.dependencies import CurrentUser
from modules.users.guards import require_user_permission
from modules.users.permissions import UserPermission
from .schemas import DailyBalanceSnapshotGenerateSchema, DailyBalanceSnapshotReadSchema
from .services import daily_balance_snapshot_service

admin_daily_balance_snapshots_router = APIRouter()


@admin_daily_balance_snapshots_router.post(
    "",
    response_model=list[DailyBalanceSnapshotReadSchema],
    status_code=status.HTTP_200_OK,
    summary="Generate daily balance snapshots (Admin)",
)
async def generate_daily_balance_snapshots(
    payload: DailyBalanceSnapshotGenerateSchema,
    current_user: Annotated[
        CurrentUser,
        Depends(
            require_user_permission(UserPermission.GENERATE_DAILY_BALANCE_SNAPSHOTS)
        ),
    ],
    db: AsyncSession = Depends(get_session),
):
    return await daily_balance_snapshot_service.generate_snapshots(
        db, payload.business_date, payload.currency, payload.account_id
    )


@admin_daily_balance_snapshots_router.get(
    "",
    response_model=list[DailyBalanceSnapshotReadSchema],
    summary="List daily balance snapshots (Staff/Admin)",
)
async def list_daily_balance_snapshots(
    current_user: Annotated[
        CurrentUser,
        Depends(require_user_permission(UserPermission.READ_DAILY_BALANCE_SNAPSHOTS)),
    ],
    business_date: date | None = Query(default=None),
    currency: AccountCurrencyEnum | None = Query(default=None),
    account_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
):
    return await daily_balance_snapshot_service.list_snapshots(
        db, business_date, currency, account_id, limit, offset
    )


@admin_daily_balance_snapshots_router.get(
    "/{snapshot_id}",
    response_model=DailyBalanceSnapshotReadSchema,
    summary="Get daily balance snapshot detail (Staff/Admin)",
)
async def get_daily_balance_snapshot(
    snapshot_id: uuid.UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_user_permission(UserPermission.READ_DAILY_BALANCE_SNAPSHOTS)),
    ],
    db: AsyncSession = Depends(get_session),
):
    return await daily_balance_snapshot_service.get_snapshot(db, snapshot_id)
