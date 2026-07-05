from enum import Enum


class NotificationTypeEnum(str, Enum):
    TRANSACTION = "transaction"
    KYC = "kyc"
    SECURITY = "security"
    SYSTEM = "system"
