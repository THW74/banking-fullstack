import uuid
from datetime import date, datetime
from pydantic import BaseModel, Field, field_validator, ConfigDict
from pydantic_extra_types.country import CountryAlpha2
from pydantic_extra_types.phone_numbers import PhoneNumber

from .enums import (
    SalutationEnum,
    GenderEnum,
    MaritalStatusEnum,
    IdentificationTypeEnum,
    EmploymentStatusEnum,
    KycStatusEnum,
)


class CustomerProfileCreateSchema(BaseModel):
    # Optional basic draft initialization
    phone_number: PhoneNumber | None = None


class CustomerProfileUpdateSchema(BaseModel):
    title: SalutationEnum | None = None
    gender: GenderEnum | None = None
    date_of_birth: date | None = None
    country_of_birth: CountryAlpha2 | None = None
    place_of_birth: str | None = None
    marital_status: MaritalStatusEnum | None = None
    nationality: CountryAlpha2 | None = None

    identification_type: IdentificationTypeEnum | None = None
    identification_number: str | None = None
    id_issue_date: date | None = None
    id_expiry_date: date | None = None

    phone_number: PhoneNumber | None = None
    address: str | None = None
    city: str | None = None
    country: CountryAlpha2 | None = None

    employment_status: EmploymentStatusEnum | None = None
    employer_name: str | None = None
    employer_address: str | None = None
    employer_city: str | None = None
    employer_country: CountryAlpha2 | None = None
    annual_income: float | None = None
    date_of_employment: date | None = None

    profile_photo_url: str | None = None
    id_photo_url: str | None = None
    signature_photo_url: str | None = None

    @field_validator("date_of_birth")
    @classmethod
    def validate_age(cls, v):
        if v:
            today = date.today()
            age = today.year - v.year - ((today.month, today.day) < (v.month, v.day))
            if age < 18:
                raise ValueError("customer must be at least 18 years old")
        return v

    @field_validator("annual_income")
    @classmethod
    def validate_income(cls, v):
        if v is not None and v < 0:
            raise ValueError("annual_income must be non-negative")
        return v

    @field_validator("date_of_employment")
    @classmethod
    def validate_doe(cls, v):
        if v and v > date.today():
            raise ValueError("date_of_employment cannot be in the future")
        return v


class CustomerProfileResponseSchema(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: SalutationEnum | None
    gender: GenderEnum | None
    date_of_birth: date | None
    country_of_birth: str | None
    place_of_birth: str | None
    marital_status: MaritalStatusEnum | None
    nationality: str | None

    identification_type: IdentificationTypeEnum | None
    identification_number: str | None
    id_issue_date: date | None
    id_expiry_date: date | None

    phone_number: str | None
    address: str | None
    city: str | None
    country: str | None

    employment_status: EmploymentStatusEnum | None
    employer_name: str | None
    employer_address: str | None
    employer_city: str | None
    employer_country: str | None
    annual_income: float | None
    date_of_employment: date | None

    profile_photo_url: str | None
    id_photo_url: str | None
    signature_photo_url: str | None

    kyc_status: KycStatusEnum
    submitted_at: datetime | None
    reviewed_at: datetime | None
    rejection_reason: str | None

    model_config = ConfigDict(from_attributes=True)


class CustomerProfileSummarySchema(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    kyc_status: KycStatusEnum
    phone_number: str | None
    submitted_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
