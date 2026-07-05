import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, TypeAlias

from pydantic import BaseModel

from modules.accounts.enums import AccountCurrencyEnum
from modules.transactions.enums import (
    LedgerEntryTypeEnum,
    TransactionStatusEnum,
    TransactionTypeEnum,
)

AccountTargetType: TypeAlias = Literal["customer_account", "internal_account"]


class TrialBalanceLineSchema(BaseModel):
    account_target_type: AccountTargetType
    account_id: uuid.UUID
    account_code: str
    account_name: str
    account_type: str
    currency: AccountCurrencyEnum
    debit_total: Decimal
    credit_total: Decimal
    net_debit: Decimal
    net_credit: Decimal
    last_posted_at: datetime


class TrialBalanceReportSchema(BaseModel):
    as_of: date
    currency: AccountCurrencyEnum
    generated_at: datetime
    total_debit: Decimal
    total_credit: Decimal
    total_net_debit: Decimal
    total_net_credit: Decimal
    is_balanced: bool
    line_count: int
    lines: list[TrialBalanceLineSchema]


class GeneralLedgerEntrySchema(BaseModel):
    ledger_entry_id: uuid.UUID
    transaction_id: uuid.UUID
    transaction_reference: str
    transaction_type: TransactionTypeEnum
    transaction_status: TransactionStatusEnum
    accounting_date: datetime
    posted_at: datetime | None

    account_target_type: AccountTargetType
    account_id: uuid.UUID
    account_code: str
    account_name: str
    account_type: str

    currency: AccountCurrencyEnum
    entry_type: LedgerEntryTypeEnum
    debit_amount: Decimal
    credit_amount: Decimal
    signed_amount: Decimal

    description: str | None
    created_by_user_id: uuid.UUID


class GeneralLedgerReportSchema(BaseModel):
    from_date: date
    to_date: date
    currency: AccountCurrencyEnum
    generated_at: datetime

    total_debit: Decimal
    total_credit: Decimal
    entry_count: int
    limit: int
    offset: int
    has_more: bool

    entries: list[GeneralLedgerEntrySchema]
