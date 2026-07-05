from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database import get_session
from modules.accounts.enums import AccountCurrencyEnum
from modules.auth.dependencies import CurrentUser
from modules.users.guards import require_user_permission
from modules.users.permissions import UserPermission
from .schemas import TrialBalanceReportSchema
from .services import report_service

admin_reports_router = APIRouter()


@admin_reports_router.get(
    "/trial-balance",
    response_model=TrialBalanceReportSchema,
    summary="Generate trial balance report (Staff/Admin)",
)
async def get_trial_balance_report(
    current_user: Annotated[
        CurrentUser,
        Depends(require_user_permission(UserPermission.READ_FINANCIAL_REPORTS)),
    ],
    currency: AccountCurrencyEnum = Query(...),
    as_of: date | None = Query(default=None),
    db: AsyncSession = Depends(get_session),
):
    return await report_service.get_trial_balance(db, currency, as_of)
