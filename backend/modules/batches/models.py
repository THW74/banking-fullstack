import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from modules.accounts.enums import AccountCurrencyEnum
from .enums import (
    EndOfDayBatchStatusEnum,
    EndOfDayValidationIssueSeverityEnum,
    EndOfDayValidationIssueTypeEnum,
)


class EndOfDayBatch(SQLModel, table=True):
    __tablename__: Any = "end_of_day_batches"
    __table_args__ = (
        UniqueConstraint("business_date", name="uq_end_of_day_batches_business_date"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    business_date: date = Field(nullable=False, index=True)
    status: EndOfDayBatchStatusEnum = Field(
        default=EndOfDayBatchStatusEnum.RUNNING, nullable=False, index=True
    )

    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    completed_at: datetime | None = None
    requested_by_user_id: uuid.UUID = Field(foreign_key="users.id", nullable=False)

    transaction_count: int = Field(default=0)
    ledger_entry_count: int = Field(default=0)
    currency_count: int = Field(default=0)
    validation_issue_count: int = Field(default=0)
    error_issue_count: int = Field(default=0)
    warning_issue_count: int = Field(default=0)
    snapshot_count: int = Field(default=0)
    snapshot_missing_count: int = Field(default=0)
    check_daily_snapshots: bool = Field(default=False)
    run_notes: str | None = Field(default=None, max_length=500)
    is_balanced: bool = Field(default=True)
    failure_reason: str | None = Field(default=None, max_length=255)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )


class EndOfDayBatchCurrencySummary(SQLModel, table=True):
    __tablename__: Any = "end_of_day_batch_currency_summaries"
    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "currency",
            name="uq_end_of_day_batch_currency_summaries_batch_currency",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    batch_id: uuid.UUID = Field(
        foreign_key="end_of_day_batches.id", nullable=False, index=True
    )
    currency: AccountCurrencyEnum = Field(nullable=False, index=True)

    transaction_count: int = Field(default=0)
    ledger_entry_count: int = Field(default=0)
    total_debit: Decimal = Field(
        default=Decimal("0.00"), max_digits=18, decimal_places=2
    )
    total_credit: Decimal = Field(
        default=Decimal("0.00"), max_digits=18, decimal_places=2
    )
    is_balanced: bool = Field(default=True)


class EndOfDayBatchValidationIssue(SQLModel, table=True):
    __tablename__: Any = "end_of_day_batch_validation_issues"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    batch_id: uuid.UUID = Field(
        foreign_key="end_of_day_batches.id", nullable=False, index=True
    )
    issue_type: EndOfDayValidationIssueTypeEnum = Field(nullable=False, index=True)
    severity: EndOfDayValidationIssueSeverityEnum = Field(
        default=EndOfDayValidationIssueSeverityEnum.ERROR,
        nullable=False,
        index=True,
    )
    message: str = Field(max_length=500, nullable=False)
    currency: AccountCurrencyEnum | None = Field(default=None, index=True)
    customer_account_id: uuid.UUID | None = Field(
        default=None, foreign_key="bank_accounts.id", index=True
    )
    transaction_id: uuid.UUID | None = Field(
        default=None, foreign_key="transactions.id", index=True
    )
    ledger_entry_id: uuid.UUID | None = Field(
        default=None, foreign_key="ledger_entries.id", index=True
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
