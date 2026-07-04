import uuid
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from pydantic_extra_types.country import CountryAlpha2
from pydantic_extra_types.phone_numbers import PhoneNumber
from .enums import RelationshipTypeEnum


class NextOfKinBaseSchema(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    relationship: RelationshipTypeEnum
    email: EmailStr | None = None
    phone_number: PhoneNumber
    address: str = Field(..., min_length=2, max_length=255)
    city: str = Field(..., min_length=1, max_length=100)
    country: CountryAlpha2
    nationality: CountryAlpha2 | None = None
    id_number: str | None = Field(default=None, max_length=100)
    passport_number: str | None = Field(default=None, max_length=100)
    is_primary: bool = False


class NextOfKinCreateSchema(NextOfKinBaseSchema):
    pass


class NextOfKinUpdateSchema(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=100)
    relationship: RelationshipTypeEnum | None = None
    email: EmailStr | None = None
    phone_number: PhoneNumber | None = None
    address: str | None = Field(default=None, min_length=2, max_length=255)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    country: CountryAlpha2 | None = None
    nationality: CountryAlpha2 | None = None
    id_number: str | None = Field(default=None, max_length=100)
    passport_number: str | None = Field(default=None, max_length=100)
    is_primary: bool | None = None


class NextOfKinReadSchema(NextOfKinBaseSchema):
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
