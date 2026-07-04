from typing import Annotated
from fastapi import Depends, HTTPException, status
from modules.auth.dependencies import CurrentUser, get_active_current_user
from .schemas import RoleChoicesSchema
from .permissions import UserPermission, can_user


def require_user_permission(permission: UserPermission):
    async def guard(
        current_user: CurrentUser = Depends(get_active_current_user),
    ) -> CurrentUser:
        if not can_user(current_user.platform_role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden"
            )
        return current_user
    return guard


def is_admin(current_user: CurrentUser) -> bool:
    return current_user.platform_role in {
        RoleChoicesSchema.ADMIN,
        RoleChoicesSchema.SUPER_ADMIN,
    }


def is_super_admin(current_user: CurrentUser) -> bool:
    return current_user.platform_role == RoleChoicesSchema.SUPER_ADMIN
