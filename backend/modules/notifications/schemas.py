import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict
from .enums import NotificationTypeEnum


class NotificationSchema(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    message: str
    notification_type: NotificationTypeEnum
    is_read: bool
    read_at: datetime | None
    source_metadata: dict[str, Any] | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationListSchema(BaseModel):
    items: list[NotificationSchema]
    total: int
    limit: int
    offset: int
    unread_count: int

    model_config = ConfigDict(from_attributes=True)
