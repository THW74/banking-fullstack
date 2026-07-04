import uuid
from datetime import date, datetime, timezone
from typing import Any
from sqlmodel import Field, SQLModel
from .enums import (
    SalutationEnum,
    GenderEnum,
    MaritalStatusEnum,
    IdentificationTypeEnum,
    EmploymentStatusEnum,
    KycStatusEnum,
)


class CustomerProfile(SQLModel, table=True):
    __tablename__: Any = "customer_profiles"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", unique=True, index=True, nullable=False)

    # Personal Information
    title: SalutationEnum | None = None
    gender: GenderEnum | None = None
    date_of_birth: date | None = None
    country_of_birth: str | None = None
    place_of_birth: str | None = None
    marital_status: MaritalStatusEnum | None = None
    nationality: str | None = None

    # Identification
    identification_type: IdentificationTypeEnum | None = None
    identification_number: str | None = None
    id_issue_date: date | None = None
    id_expiry_date: date | None = None

    # Contact & Address
    phone_number: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None

    # Employment & Income
    employment_status: EmploymentStatusEnum | None = None
    employer_name: str | None = None
    employer_address: str | None = None
    employer_city: str | None = None
    employer_country: str | None = None
    annual_income: float | None = None
    date_of_employment: date | None = None

    # Temporary Photo Fields (Optional in draft; id_photo_url required in submit)
    profile_photo_url: str | None = None
    id_photo_url: str | None = None
    signature_photo_url: str | None = None

    # KYC Audit Metadata
    kyc_status: KycStatusEnum = Field(default=KycStatusEnum.DRAFT)
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    reviewed_by_user_id: uuid.UUID | None = None
    rejection_reason: str | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
