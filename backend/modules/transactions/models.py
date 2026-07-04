import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlmodel import Field, SQLModel

from modules.accounts.enums import AccountCurrencyEnum
from .enums import TransactionTypeEnum, TransactionStatusEnum, LedgerEntryTypeEnum


class Transaction(SQLModel, table=True):
    __tablename__: Any = "transactions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    reference: str = Field(unique=True, index=True, nullable=False, max_length=64)

    transaction_type: TransactionTypeEnum = Field(nullable=False)
    status: TransactionStatusEnum = Field(
        default=TransactionStatusEnum.POSTED, nullable=False
    )

    source_account_id: uuid.UUID | None = Field(
        default=None, foreign_key="bank_accounts.id"
    )
    destination_account_id: uuid.UUID | None = Field(
        default=None, foreign_key="bank_accounts.id"
    )

    amount: Decimal = Field(max_digits=18, decimal_places=2, nullable=False)
    fee_amount: Decimal = Field(
        default=Decimal("0.00"), max_digits=18, decimal_places=2, nullable=False
    )
    total_debit_amount: Decimal = Field(
        default=Decimal("0.00"), max_digits=18, decimal_places=2, nullable=False
    )
    currency: AccountCurrencyEnum = Field(nullable=False)

    description: str | None = Field(default=None, max_length=255)
    created_by_user_id: uuid.UUID = Field(foreign_key="users.id", nullable=False)

    reversed_transaction_id: uuid.UUID | None = Field(
        default=None, foreign_key="transactions.id", index=True
    )
    reversed_by_transaction_id: uuid.UUID | None = Field(
        default=None, foreign_key="transactions.id", index=True
    )
    reversal_reason: str | None = Field(default=None, max_length=255)
    reversed_at: datetime | None = None
    reversed_by_user_id: uuid.UUID | None = Field(default=None, foreign_key="users.id")

    posted_at: datetime | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )


class FeeRule(SQLModel, table=True):
    __tablename__: Any = "fee_rules"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    transaction_type: TransactionTypeEnum = Field(nullable=False, index=True)
    currency: AccountCurrencyEnum = Field(nullable=False, index=True)

    fixed_amount: Decimal = Field(
        default=Decimal("0.00"), max_digits=18, decimal_places=2
    )
    percentage_rate: Decimal = Field(
        default=Decimal("0.00"), max_digits=8, decimal_places=6
    )
    min_fee: Decimal = Field(default=Decimal("0.00"), max_digits=18, decimal_places=2)
    max_fee: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)

    is_active: bool = Field(default=True, index=True)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )


class LedgerEntry(SQLModel, table=True):
    __tablename__: Any = "ledger_entries"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    transaction_id: uuid.UUID = Field(
        foreign_key="transactions.id", index=True, nullable=False
    )
    customer_account_id: uuid.UUID | None = Field(
        default=None, foreign_key="bank_accounts.id", index=True
    )
    internal_account_id: uuid.UUID | None = Field(
        default=None, foreign_key="internal_accounts.id", index=True
    )

    entry_type: LedgerEntryTypeEnum = Field(nullable=False)
    amount: Decimal = Field(max_digits=18, decimal_places=2, nullable=False)
    currency: AccountCurrencyEnum = Field(nullable=False)

    balance_after: Decimal = Field(max_digits=18, decimal_places=2, nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
