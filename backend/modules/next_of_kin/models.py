import uuid
from datetime import datetime, timezone
from typing import Any
from sqlmodel import Field, SQLModel
from .enums import RelationshipTypeEnum


class NextOfKin(SQLModel, table=True):
    __tablename__: Any = "next_of_kin"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True, nullable=False)

    full_name: str = Field(max_length=100, nullable=False)
    relationship: RelationshipTypeEnum
    email: str | None = Field(default=None, max_length=255)
    phone_number: str = Field(nullable=False)
    address: str = Field(max_length=255, nullable=False)
    city: str = Field(max_length=100, nullable=False)
    country: str = Field(max_length=2, nullable=False)
    nationality: str | None = Field(default=None, max_length=2)

    id_number: str | None = Field(default=None, max_length=100)
    passport_number: str | None = Field(default=None, max_length=100)
    is_primary: bool = Field(default=False)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
