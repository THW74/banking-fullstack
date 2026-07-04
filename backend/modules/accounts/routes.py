import uuid
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from typing import Annotated
from infrastructure.database import get_session
from modules.auth.dependencies import ActiveCurrentUserDep, CurrentUser
from modules.users.guards import require_user_permission
from modules.users.permissions import UserPermission
from .schemas import BankAccountCreateSchema, BankAccountUpdateSchema, BankAccountReadSchema
from .services import bank_account_service
from .enums import AccountStatusEnum

customer_accounts_router = APIRouter()
admin_accounts_router = APIRouter()


# --- CUSTOMER ENDPOINTS ---

@customer_accounts_router.get(
    "",
    response_model=list[BankAccountReadSchema],
    summary="List active customer bank accounts"
)
async def list_customer_accounts(
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session)
):
    return await bank_account_service.list_customer_accounts(db, current_user.user_id)


@customer_accounts_router.get(
    "/{account_id}",
    response_model=BankAccountReadSchema,
    summary="Get customer bank account details"
)
async def get_customer_account(
    account_id: uuid.UUID,
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session)
):
    return await bank_account_service.get_customer_account(db, account_id, current_user.user_id)


# --- ADMIN / STAFF ENDPOINTS ---

@admin_accounts_router.get(
    "",
    response_model=list[BankAccountReadSchema],
    summary="List all bank accounts (Staff/Admin)"
)
async def list_all_accounts(
    current_user: Annotated[CurrentUser, Depends(require_user_permission(UserPermission.READ_BANK_ACCOUNTS))],
    status_filter: AccountStatusEnum | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session)
):
    return await bank_account_service.list_all_accounts(db, status_filter, limit, offset)


@admin_accounts_router.get(
    "/{account_id}",
    response_model=BankAccountReadSchema,
    summary="Get bank account details (Staff/Admin)"
)
async def get_account_for_admin(
    account_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_user_permission(UserPermission.READ_BANK_ACCOUNTS))],
    db: AsyncSession = Depends(get_session)
):
    return await bank_account_service.get_account_by_id_for_admin(db, account_id)


@admin_accounts_router.post(
    "",
    response_model=BankAccountReadSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Open a bank account (Staff/Admin)"
)
async def create_bank_account(
    payload: BankAccountCreateSchema,
    current_user: Annotated[CurrentUser, Depends(require_user_permission(UserPermission.CREATE_BANK_ACCOUNTS))],
    db: AsyncSession = Depends(get_session)
):
    return await bank_account_service.create_bank_account(db, payload)


@admin_accounts_router.post(
    "/{account_id}/freeze",
    response_model=BankAccountReadSchema,
    summary="Freeze a bank account (Staff/Admin)"
)
async def freeze_account(
    account_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_user_permission(UserPermission.MANAGE_BANK_ACCOUNT_STATUS))],
    db: AsyncSession = Depends(get_session)
):
    return await bank_account_service.freeze_account(db, account_id)


@admin_accounts_router.post(
    "/{account_id}/close",
    response_model=BankAccountReadSchema,
    summary="Close a bank account (Staff/Admin)"
)
async def close_account(
    account_id: uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(require_user_permission(UserPermission.MANAGE_BANK_ACCOUNT_STATUS))],
    db: AsyncSession = Depends(get_session)
):
    return await bank_account_service.close_account(db, account_id)
