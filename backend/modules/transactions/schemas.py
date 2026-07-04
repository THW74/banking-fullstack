import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from modules.accounts.enums import AccountCurrencyEnum
from .enums import TransactionTypeEnum, TransactionStatusEnum, LedgerEntryTypeEnum


# --- Request schemas ---


class CustomerTransferSchema(BaseModel):
    source_account_id: uuid.UUID
    destination_account_id: uuid.UUID
    amount: Decimal = Field(gt=Decimal("0.00"))
    description: str | None = Field(default=None, max_length=255)


class AdminDepositSchema(BaseModel):
    destination_account_id: uuid.UUID
    amount: Decimal = Field(gt=Decimal("0.00"))
    description: str | None = Field(default=None, max_length=255)


class AdminWithdrawalSchema(BaseModel):
    source_account_id: uuid.UUID
    amount: Decimal = Field(gt=Decimal("0.00"))
    description: str | None = Field(default=None, max_length=255)


# --- Response schemas ---


class TransactionReadSchema(BaseModel):
    id: uuid.UUID
    reference: str
    transaction_type: TransactionTypeEnum
    status: TransactionStatusEnum
    source_account_id: uuid.UUID | None
    destination_account_id: uuid.UUID | None
    amount: Decimal
    currency: AccountCurrencyEnum
    description: str | None
    created_by_user_id: uuid.UUID
    posted_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LedgerEntryReadSchema(BaseModel):
    id: uuid.UUID
    transaction_id: uuid.UUID
    account_id: uuid.UUID
    entry_type: LedgerEntryTypeEnum
    amount: Decimal
    currency: AccountCurrencyEnum
    balance_after: Decimal
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
