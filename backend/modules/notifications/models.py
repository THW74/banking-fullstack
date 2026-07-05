import uuid
from datetime import datetime, timezone
from typing import Any
from sqlmodel import Field, SQLModel, Column, JSON
from .enums import NotificationTypeEnum


class Notification(SQLModel, table=True):
    __tablename__: Any = "notifications"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True, nullable=False)
    title: str = Field(nullable=False)
    message: str = Field(nullable=False)
    notification_type: NotificationTypeEnum = Field(nullable=False, index=True)
    is_read: bool = Field(default=False, nullable=False, index=True)
    read_at: datetime | None = Field(default=None)
    source_metadata: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        index=True,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
