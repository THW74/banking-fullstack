import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database import get_session
from modules.accounts.enums import AccountCurrencyEnum
from modules.auth.dependencies import CurrentUser
from modules.transactions.enums import TransactionTypeEnum
from modules.users.guards import require_user_permission
from modules.users.permissions import UserPermission
from .schemas import (
    AccountTargetType,
    GeneralLedgerAccountSummaryReportSchema,
    GeneralLedgerReportSchema,
    TrialBalanceReportSchema,
)
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


@admin_reports_router.get(
    "/general-ledger/accounts",
    response_model=GeneralLedgerAccountSummaryReportSchema,
    summary="Generate general ledger account summary report (Staff/Admin)",
)
async def get_general_ledger_account_summary_report(
    current_user: Annotated[
        CurrentUser,
        Depends(require_user_permission(UserPermission.READ_FINANCIAL_REPORTS)),
    ],
    currency: AccountCurrencyEnum = Query(...),
    from_date: date = Query(...),
    to_date: date = Query(...),
    account_target_type: AccountTargetType | None = Query(default=None),
    account_id: uuid.UUID | None = Query(default=None),
    account_code: str | None = Query(default=None),
    transaction_type: TransactionTypeEnum | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
):
    return await report_service.get_general_ledger_account_summary(
        db,
        currency,
        from_date,
        to_date,
        account_target_type,
        account_id,
        account_code,
        transaction_type,
        limit,
        offset,
    )


@admin_reports_router.get(
    "/general-ledger",
    response_model=GeneralLedgerReportSchema,
    summary="Generate general ledger activity report (Staff/Admin)",
)
async def get_general_ledger_report(
    current_user: Annotated[
        CurrentUser,
        Depends(require_user_permission(UserPermission.READ_FINANCIAL_REPORTS)),
    ],
    currency: AccountCurrencyEnum = Query(...),
    from_date: date = Query(...),
    to_date: date = Query(...),
    account_target_type: AccountTargetType | None = Query(default=None),
    account_id: uuid.UUID | None = Query(default=None),
    account_code: str | None = Query(default=None),
    transaction_type: TransactionTypeEnum | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
):
    return await report_service.get_general_ledger(
        db,
        currency,
        from_date,
        to_date,
        account_target_type,
        account_id,
        account_code,
        transaction_type,
        limit,
        offset,
    )
