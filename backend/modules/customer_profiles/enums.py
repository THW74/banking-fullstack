from enum import Enum


class SalutationEnum(str, Enum):
    MR = "mr"
    MRS = "mrs"
    MS = "ms"
    DR = "dr"
    PROF = "prof"


class GenderEnum(str, Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class MaritalStatusEnum(str, Enum):
    SINGLE = "single"
    MARRIED = "married"
    DIVORCED = "divorced"
    WIDOWED = "widowed"


class IdentificationTypeEnum(str, Enum):
    NATIONAL_ID = "national_id"
    PASSPORT = "passport"
    DRIVERS_LICENSE = "drivers_license"
    RESIDENCE_PERMIT = "residence_permit"


class EmploymentStatusEnum(str, Enum):
    EMPLOYED = "employed"
    SELF_EMPLOYED = "self_employed"
    UNEMPLOYED = "unemployed"
    RETIRED = "retired"
    STUDENT = "student"
    HOMEMAKER = "homemaker"


class KycStatusEnum(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
