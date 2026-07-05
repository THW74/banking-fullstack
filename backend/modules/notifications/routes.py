import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from infrastructure.database import get_session
from modules.auth.dependencies import ActiveCurrentUserDep, CurrentUser
from modules.users.guards import require_user_permission
from modules.users.permissions import UserPermission

from .schemas import NotificationSchema, NotificationListSchema
from .services import notification_service
from .enums import NotificationTypeEnum

customer_notifications_router = APIRouter()
admin_notifications_router = APIRouter()


# --- CUSTOMER ENDPOINTS ---

@customer_notifications_router.get(
    "",
    response_model=NotificationListSchema,
    summary="Get current user's notifications",
)
async def get_my_notifications(
    current_user: ActiveCurrentUserDep,
    unread_only: bool = Query(default=False),
    notification_type: NotificationTypeEnum | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
):
    items, total, unread_count = await notification_service.get_user_notifications(
        db, current_user.user_id, limit, offset, unread_only, notification_type
    )
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "unread_count": unread_count,
    }


@customer_notifications_router.post(
    "/{notification_id}/read",
    response_model=NotificationSchema,
    summary="Mark a specific notification as read",
)
async def read_notification(
    notification_id: uuid.UUID,
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session),
):
    return await notification_service.mark_as_read(
        db, notification_id, current_user.user_id
    )


@customer_notifications_router.post(
    "/read-all",
    summary="Mark all current user's notifications as read",
)
async def read_all_notifications(
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session),
):
    count = await notification_service.mark_all_as_read(db, current_user.user_id)
    return {"message": "Success", "updated_count": count}


# --- ADMIN ENDPOINTS ---

@admin_notifications_router.get(
    "",
    summary="Audit/List notifications across all users",
)
async def list_notifications_admin(
    user_id: uuid.UUID | None = Query(default=None),
    notification_type: NotificationTypeEnum | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: CurrentUser = Depends(
        require_user_permission(UserPermission.READ_NOTIFICATIONS)
    ),
    db: AsyncSession = Depends(get_session),
):
    items, total = await notification_service.get_admin_notifications(
        db, limit, offset, user_id, notification_type
    )
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
