import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlmodel import Field, SQLModel

from modules.accounts.enums import AccountCurrencyEnum, AccountTypeEnum
from .enums import ProductStatusEnum


class AccountProduct(SQLModel, table=True):
    __tablename__: Any = "account_products"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    code: str = Field(unique=True, index=True, nullable=False, max_length=32)
    name: str = Field(max_length=100, nullable=False)
    description: str | None = Field(default=None, max_length=255)

    account_type: AccountTypeEnum = Field(nullable=False, index=True)
    currency: AccountCurrencyEnum = Field(nullable=False, index=True)
    status: ProductStatusEnum = Field(default=ProductStatusEnum.DRAFT, index=True)

    interest_rate: Decimal = Field(
        default=Decimal("0.00"), max_digits=5, decimal_places=2
    )
    minimum_opening_deposit: Decimal = Field(
        default=Decimal("0.00"), max_digits=18, decimal_places=2
    )
    minimum_balance: Decimal = Field(
        default=Decimal("0.00"), max_digits=18, decimal_places=2
    )
    monthly_fee: Decimal = Field(
        default=Decimal("0.00"), max_digits=18, decimal_places=2
    )

    fixed_deposit_term_months: int | None = None
    early_withdrawal_penalty_rate: Decimal | None = Field(
        default=None, max_digits=5, decimal_places=2
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
