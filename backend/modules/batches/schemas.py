import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from modules.accounts.enums import AccountCurrencyEnum
from .enums import (
    EndOfDayBatchStatusEnum,
    EndOfDayValidationIssueSeverityEnum,
    EndOfDayValidationIssueTypeEnum,
)


class EndOfDayBatchRunSchema(BaseModel):
    business_date: date
    run_notes: str | None = Field(default=None, max_length=500)
    check_daily_snapshots: bool = False


class EndOfDayBatchCurrencySummaryReadSchema(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    currency: AccountCurrencyEnum
    transaction_count: int
    ledger_entry_count: int
    total_debit: Decimal
    total_credit: Decimal
    is_balanced: bool

    model_config = ConfigDict(from_attributes=True)


class EndOfDayBatchValidationIssueReadSchema(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    issue_type: EndOfDayValidationIssueTypeEnum
    severity: EndOfDayValidationIssueSeverityEnum
    message: str
    currency: AccountCurrencyEnum | None
    customer_account_id: uuid.UUID | None
    transaction_id: uuid.UUID | None
    ledger_entry_id: uuid.UUID | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EndOfDayBatchReadSchema(BaseModel):
    id: uuid.UUID
    business_date: date
    status: EndOfDayBatchStatusEnum
    started_at: datetime
    completed_at: datetime | None
    requested_by_user_id: uuid.UUID
    transaction_count: int
    ledger_entry_count: int
    currency_count: int
    validation_issue_count: int
    error_issue_count: int
    warning_issue_count: int
    snapshot_count: int
    snapshot_missing_count: int
    check_daily_snapshots: bool
    run_notes: str | None
    is_balanced: bool
    failure_reason: str | None
    summaries: list[EndOfDayBatchCurrencySummaryReadSchema] = []
    validation_issues: list[EndOfDayBatchValidationIssueReadSchema] = []

    model_config = ConfigDict(from_attributes=True)
