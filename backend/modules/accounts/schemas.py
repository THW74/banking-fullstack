import uuid
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field
from .enums import (
    AccountCurrencyEnum,
    AccountStatusEnum,
    AccountTypeEnum,
    InternalAccountTypeEnum,
)


class BankAccountCreateSchema(BaseModel):
    user_id: uuid.UUID
    product_id: uuid.UUID
    account_name: str = Field(..., min_length=2, max_length=100)
    is_primary: bool = False


class BankAccountUpdateSchema(BaseModel):
    account_name: str | None = Field(default=None, min_length=2, max_length=100)
    is_primary: bool | None = None
    account_status: AccountStatusEnum | None = None
    interest_rate: Decimal | None = Field(default=None, ge=Decimal("0.00"))


class BankAccountReadSchema(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    product_id: uuid.UUID | None
    account_number: str
    account_name: str
    account_type: AccountTypeEnum
    currency: AccountCurrencyEnum
    account_status: AccountStatusEnum
    available_balance: Decimal
    current_balance: Decimal
    is_primary: bool
    interest_rate: Decimal
    minimum_balance: Decimal
    monthly_fee: Decimal
    fixed_deposit_term_months: int | None
    fixed_deposit_maturity_date: date | None
    early_withdrawal_penalty_rate: Decimal | None
    opened_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InternalAccountReadSchema(BaseModel):
    id: uuid.UUID
    account_code: str
    account_name: str
    account_type: InternalAccountTypeEnum
    currency: AccountCurrencyEnum
    balance: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
