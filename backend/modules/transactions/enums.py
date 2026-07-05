from enum import Enum


class TransactionTypeEnum(str, Enum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRANSFER = "transfer"
    INTEREST_POSTING = "interest_posting"
    REVERSAL = "reversal"


class TransactionStatusEnum(str, Enum):
    POSTED = "posted"
    FAILED = "failed"
    REVERSED = "reversed"


class LedgerEntryTypeEnum(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"
