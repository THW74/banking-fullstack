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
    currency: AccountCurrencyEnum = Field(nullable=False)

    description: str | None = Field(default=None, max_length=255)
    created_by_user_id: uuid.UUID = Field(foreign_key="users.id", nullable=False)

    posted_at: datetime | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )


class LedgerEntry(SQLModel, table=True):
    __tablename__: Any = "ledger_entries"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    transaction_id: uuid.UUID = Field(
        foreign_key="transactions.id", index=True, nullable=False
    )
    account_id: uuid.UUID = Field(
        foreign_key="bank_accounts.id", index=True, nullable=False
    )

    entry_type: LedgerEntryTypeEnum = Field(nullable=False)
    amount: Decimal = Field(max_digits=18, decimal_places=2, nullable=False)
    currency: AccountCurrencyEnum = Field(nullable=False)

    balance_after: Decimal = Field(max_digits=18, decimal_places=2, nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
