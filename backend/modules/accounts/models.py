import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from sqlmodel import Field, SQLModel
from .enums import AccountTypeEnum, AccountCurrencyEnum, AccountStatusEnum


class BankAccount(SQLModel, table=True):
    __tablename__: Any = "bank_accounts"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True, nullable=False)

    account_number: str = Field(unique=True, index=True, nullable=False, max_length=32)
    account_name: str = Field(max_length=100, nullable=False)

    account_type: AccountTypeEnum
    currency: AccountCurrencyEnum
    account_status: AccountStatusEnum = Field(default=AccountStatusEnum.PENDING)

    available_balance: Decimal = Field(default=Decimal("0.00"), max_digits=18, decimal_places=2)
    current_balance: Decimal = Field(default=Decimal("0.00"), max_digits=18, decimal_places=2)

    is_primary: bool = Field(default=False)
    interest_rate: Decimal = Field(default=Decimal("0.00"), max_digits=5, decimal_places=2)

    opened_at: datetime | None = None
    closed_at: datetime | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
