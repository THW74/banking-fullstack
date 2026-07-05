import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from modules.accounts.enums import AccountCurrencyEnum


class DailyBalanceSnapshot(SQLModel, table=True):
    __tablename__: Any = "daily_balance_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "business_date",
            "currency",
            name="uq_daily_balance_snapshots_account_date_currency",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(
        foreign_key="bank_accounts.id", index=True, nullable=False
    )
    business_date: date = Field(nullable=False, index=True)
    currency: AccountCurrencyEnum = Field(nullable=False, index=True)

    opening_balance: Decimal = Field(
        default=Decimal("0.00"), max_digits=18, decimal_places=2
    )
    closing_balance: Decimal = Field(
        default=Decimal("0.00"), max_digits=18, decimal_places=2
    )
    available_balance: Decimal = Field(
        default=Decimal("0.00"), max_digits=18, decimal_places=2
    )
    current_balance: Decimal = Field(
        default=Decimal("0.00"), max_digits=18, decimal_places=2
    )
    debit_total: Decimal = Field(
        default=Decimal("0.00"), max_digits=18, decimal_places=2
    )
    credit_total: Decimal = Field(
        default=Decimal("0.00"), max_digits=18, decimal_places=2
    )
    transaction_count: int = Field(default=0)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
