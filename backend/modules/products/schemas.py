import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modules.accounts.enums import AccountCurrencyEnum, AccountTypeEnum
from .enums import ProductStatusEnum


class ProductCreateSchema(BaseModel):
    code: str = Field(..., min_length=2, max_length=32)
    name: str = Field(..., min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=255)

    account_type: AccountTypeEnum
    currency: AccountCurrencyEnum

    interest_rate: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    minimum_opening_deposit: Decimal = Field(
        default=Decimal("0.00"), ge=Decimal("0.00")
    )
    minimum_balance: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    monthly_fee: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))

    fixed_deposit_term_months: int | None = Field(default=None, ge=1)
    early_withdrawal_penalty_rate: Decimal | None = Field(
        default=None, ge=Decimal("0.00")
    )

    @model_validator(mode="after")
    def validate_fixed_deposit_terms(self) -> "ProductCreateSchema":
        is_fixed_deposit = self.account_type == AccountTypeEnum.FIXED_DEPOSIT
        has_fixed_deposit_terms = (
            self.fixed_deposit_term_months is not None
            or self.early_withdrawal_penalty_rate is not None
        )

        if is_fixed_deposit and self.fixed_deposit_term_months is None:
            raise ValueError(
                "fixed_deposit_term_months is required for fixed_deposit products"
            )

        if not is_fixed_deposit and has_fixed_deposit_terms:
            raise ValueError(
                "fixed_deposit_term_months and early_withdrawal_penalty_rate "
                "are only valid for fixed_deposit products"
            )

        return self


class ProductUpdateSchema(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    interest_rate: Decimal | None = Field(default=None, ge=Decimal("0.00"))
    minimum_opening_deposit: Decimal | None = Field(
        default=None, ge=Decimal("0.00")
    )
    minimum_balance: Decimal | None = Field(default=None, ge=Decimal("0.00"))
    monthly_fee: Decimal | None = Field(default=None, ge=Decimal("0.00"))

    model_config = ConfigDict(extra="forbid")


class ProductReadSchema(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    account_type: AccountTypeEnum
    currency: AccountCurrencyEnum
    status: ProductStatusEnum
    interest_rate: Decimal
    minimum_opening_deposit: Decimal
    minimum_balance: Decimal
    monthly_fee: Decimal
    fixed_deposit_term_months: int | None
    early_withdrawal_penalty_rate: Decimal | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
