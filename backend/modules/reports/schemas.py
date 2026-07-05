import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from modules.accounts.enums import AccountCurrencyEnum


class TrialBalanceLineSchema(BaseModel):
    account_target_type: Literal["customer_account", "internal_account"]
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
