import uuid
from datetime import datetime, timezone
from typing import Any
from sqlmodel import Field, SQLModel
from .schemas import SecurityQuestionsSchema, AccountStatusSchema, RoleChoicesSchema


class User(SQLModel, table=True):
    __tablename__: Any = "users"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True, index=True)
    username: str | None = Field(default=None, unique=True, nullable=True, max_length=12)
    email: str = Field(unique=True, index=True, nullable=False, max_length=255)
    full_name: str = Field(nullable=False, max_length=100)
    id_no: int = Field(unique=True, nullable=False)
    hashed_password: str = Field(nullable=False)
    is_active: bool = Field(default=False, nullable=False)
    is_superuser: bool = Field(default=False, nullable=False)
    security_question: SecurityQuestionsSchema = Field(nullable=False)
    security_answer_hash: str = Field(nullable=False)
    account_status: AccountStatusSchema = Field(default=AccountStatusSchema.INACTIVE, nullable=False)
    role: RoleChoicesSchema = Field(default=RoleChoicesSchema.CUSTOMER, nullable=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
