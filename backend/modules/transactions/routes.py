import uuid

from typing import Annotated
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database import get_session
from modules.auth.dependencies import ActiveCurrentUserDep, CurrentUser
from modules.users.guards import require_user_permission
from modules.users.permissions import UserPermission
from .schemas import (
    CustomerTransferSchema,
    AdminDepositSchema,
    AdminWithdrawalSchema,
    LedgerEntryReadSchema,
    TransactionReversalSchema,
    TransactionReadSchema,
)
from .services import transaction_service

customer_transactions_router = APIRouter()
admin_transactions_router = APIRouter()


# --- CUSTOMER ENDPOINTS ---


@customer_transactions_router.get(
    "",
    response_model=list[TransactionReadSchema],
    summary="List customer transactions",
)
async def list_customer_transactions(
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session),
):
    return await transaction_service.list_transactions_for_user(db, current_user.user_id)


@customer_transactions_router.get(
    "/{transaction_id}/ledger-entries",
    response_model=list[LedgerEntryReadSchema],
    summary="Get customer transaction ledger entries",
)
async def get_customer_transaction_ledger_entries(
    transaction_id: uuid.UUID,
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session),
):
    return await transaction_service.get_ledger_entries_for_transaction_user(
        db, transaction_id, current_user.user_id
    )


@customer_transactions_router.get(
    "/{transaction_id}",
    response_model=TransactionReadSchema,
    summary="Get customer transaction detail",
)
async def get_customer_transaction(
    transaction_id: uuid.UUID,
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session),
):
    return await transaction_service.get_transaction_for_user(
        db, transaction_id, current_user.user_id
    )


@customer_transactions_router.post(
    "/transfer",
    response_model=TransactionReadSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Transfer funds between accounts",
)
async def customer_transfer(
    payload: CustomerTransferSchema,
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session),
):
    return await transaction_service.transfer_between_accounts(
        db, current_user.user_id, payload
    )


# --- ADMIN / STAFF ENDPOINTS ---


@admin_transactions_router.get(
    "",
    response_model=list[TransactionReadSchema],
    summary="List all transactions (Staff/Admin)",
)
async def list_all_transactions(
    current_user: Annotated[
        CurrentUser,
        Depends(require_user_permission(UserPermission.READ_TRANSACTIONS)),
    ],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
):
    return await transaction_service.list_all_transactions(db, limit, offset)


@admin_transactions_router.get(
    "/{transaction_id}/ledger-entries",
    response_model=list[LedgerEntryReadSchema],
    summary="Get transaction ledger entries (Staff/Admin)",
)
async def get_transaction_ledger_entries_for_admin(
    transaction_id: uuid.UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_user_permission(UserPermission.READ_TRANSACTIONS)),
    ],
    db: AsyncSession = Depends(get_session),
):
    return await transaction_service.get_ledger_entries_for_transaction_admin(
        db, transaction_id
    )


@admin_transactions_router.get(
    "/{transaction_id}",
    response_model=TransactionReadSchema,
    summary="Get transaction detail (Staff/Admin)",
)
async def get_transaction_for_admin(
    transaction_id: uuid.UUID,
    current_user: Annotated[
        CurrentUser,
        Depends(require_user_permission(UserPermission.READ_TRANSACTIONS)),
    ],
    db: AsyncSession = Depends(get_session),
):
    return await transaction_service.get_transaction_by_id(db, transaction_id)


@admin_transactions_router.post(
    "/deposit",
    response_model=TransactionReadSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Admin deposit into customer account",
)
async def admin_deposit(
    payload: AdminDepositSchema,
    current_user: Annotated[
        CurrentUser,
        Depends(require_user_permission(UserPermission.POST_BANK_TRANSACTIONS)),
    ],
    db: AsyncSession = Depends(get_session),
):
    return await transaction_service.admin_deposit(
        db, current_user.user_id, payload
    )


@admin_transactions_router.post(
    "/withdrawal",
    response_model=TransactionReadSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Admin withdrawal from customer account",
)
async def admin_withdrawal(
    payload: AdminWithdrawalSchema,
    current_user: Annotated[
        CurrentUser,
        Depends(require_user_permission(UserPermission.POST_BANK_TRANSACTIONS)),
    ],
    db: AsyncSession = Depends(get_session),
):
    return await transaction_service.admin_withdrawal(
        db, current_user.user_id, payload
    )


@admin_transactions_router.post(
    "/{transaction_id}/reverse",
    response_model=TransactionReadSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Reverse a posted transaction (Staff/Admin)",
)
async def reverse_transaction(
    transaction_id: uuid.UUID,
    payload: TransactionReversalSchema,
    current_user: Annotated[
        CurrentUser,
        Depends(require_user_permission(UserPermission.REVERSE_BANK_TRANSACTIONS)),
    ],
    db: AsyncSession = Depends(get_session),
):
    return await transaction_service.reverse_transaction(
        db, transaction_id, current_user.user_id, payload
    )
