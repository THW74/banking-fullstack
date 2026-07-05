import uuid
from datetime import datetime, timezone
from typing import Any
from fastapi import HTTPException, status
from sqlmodel import select, func, col
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from .models import Notification
from .enums import NotificationTypeEnum


class NotificationService:
    async def create_notification(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        title: str,
        message: str,
        notification_type: NotificationTypeEnum,
        source_metadata: dict[str, Any] | None = None,
    ) -> Notification:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        notification = Notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type=notification_type,
            source_metadata=source_metadata,
            created_at=now,
            updated_at=now,
        )
        db.add(notification)
        await db.commit()
        await db.refresh(notification)
        return notification

    async def get_user_notifications(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
        unread_only: bool = False,
        notification_type: NotificationTypeEnum | None = None,
    ) -> tuple[list[Notification], int, int]:
        # Unread count (total unread notifications for this user, ignoring filters and pagination)
        unread_stmt = select(func.count(col(Notification.id))).where(
            col(Notification.user_id) == user_id,
            col(Notification.is_read) == False,
        )
        unread_res = await db.execute(unread_stmt)
        unread_count = unread_res.scalar() or 0

        # Build filtered query
        base_query = select(Notification).where(col(Notification.user_id) == user_id)
        if unread_only:
            base_query = base_query.where(col(Notification.is_read) == False)
        if notification_type is not None:
            base_query = base_query.where(col(Notification.notification_type) == notification_type)

        # Total matching query
        total_stmt = select(func.count()).select_from(base_query.subquery())
        total_res = await db.execute(total_stmt)
        total = total_res.scalar() or 0

        # Paginated items query
        items_stmt = (
            base_query.order_by(col(Notification.created_at).desc())
            .offset(offset)
            .limit(limit)
        )
        items_res = await db.execute(items_stmt)
        items = list(items_res.scalars().all())

        return items, total, unread_count

    async def mark_as_read(
        self, db: AsyncSession, notification_id: uuid.UUID, user_id: uuid.UUID
    ) -> Notification:
        statement = select(Notification).where(
            col(Notification.id) == notification_id, col(Notification.user_id) == user_id
        )
        result = await db.execute(statement)
        notification = result.scalar_one_or_none()
        if not notification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found",
            )

        if not notification.is_read:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            notification.is_read = True
            notification.read_at = now
            notification.updated_at = now
            db.add(notification)
            await db.commit()
            await db.refresh(notification)

        return notification

    async def mark_all_as_read(self, db: AsyncSession, user_id: uuid.UUID) -> int:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        stmt = (
            update(Notification)
            .where(col(Notification.user_id) == user_id)
            .where(col(Notification.is_read) == False)
            .values(is_read=True, read_at=now, updated_at=now)
        )
        res = await db.execute(stmt)
        await db.commit()
        from sqlalchemy.engine import CursorResult
        from typing import cast
        return cast(CursorResult, res).rowcount or 0

    async def get_admin_notifications(
        self,
        db: AsyncSession,
        limit: int = 50,
        offset: int = 0,
        user_id: uuid.UUID | None = None,
        notification_type: NotificationTypeEnum | None = None,
    ) -> tuple[list[Notification], int]:
        base_query = select(Notification)
        if user_id is not None:
            base_query = base_query.where(col(Notification.user_id) == user_id)
        if notification_type is not None:
            base_query = base_query.where(col(Notification.notification_type) == notification_type)

        total_stmt = select(func.count()).select_from(base_query.subquery())
        total_res = await db.execute(total_stmt)
        total = total_res.scalar() or 0

        items_stmt = (
            base_query.order_by(col(Notification.created_at).desc())
            .offset(offset)
            .limit(limit)
        )
        items_res = await db.execute(items_stmt)
        items = list(items_res.scalars().all())

        return items, total


notification_service = NotificationService()
