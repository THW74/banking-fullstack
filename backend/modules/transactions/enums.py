from enum import Enum


class TransactionTypeEnum(str, Enum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRANSFER = "transfer"


class TransactionStatusEnum(str, Enum):
    POSTED = "posted"
    FAILED = "failed"


class LedgerEntryTypeEnum(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"
