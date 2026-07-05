import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from modules.accounts.enums import AccountCurrencyEnum


class DailyBalanceSnapshotGenerateSchema(BaseModel):
    business_date: date
    currency: AccountCurrencyEnum | None = None
    account_id: uuid.UUID | None = None


class DailyBalanceSnapshotReadSchema(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    business_date: date
    currency: AccountCurrencyEnum
    opening_balance: Decimal
    closing_balance: Decimal
    available_balance: Decimal
    current_balance: Decimal
    debit_total: Decimal
    credit_total: Decimal
    transaction_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
