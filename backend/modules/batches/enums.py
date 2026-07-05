from enum import Enum


class EndOfDayBatchStatusEnum(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EndOfDayValidationIssueTypeEnum(str, Enum):
    INVALID_LEDGER_TARGET = "invalid_ledger_target"
    MISSING_LEDGER_ENTRIES = "missing_ledger_entries"
    UNBALANCED_TRANSACTION = "unbalanced_transaction"
    CURRENCY_MISMATCH = "currency_mismatch"
    FAILED_TRANSACTION_HAS_LEDGER_ENTRIES = "failed_transaction_has_ledger_entries"
