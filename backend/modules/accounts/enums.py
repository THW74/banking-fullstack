from enum import Enum


class AccountTypeEnum(str, Enum):
    SAVINGS = "savings"
    CURRENT = "current"
    CHECKING = "checking"
    FIXED_DEPOSIT = "fixed_deposit"


class AccountCurrencyEnum(str, Enum):
    USD = "USD"
    EUR = "EUR"
    DKK = "DKK"
    GBP = "GBP"


class AccountStatusEnum(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    FROZEN = "frozen"
    CLOSED = "closed"
