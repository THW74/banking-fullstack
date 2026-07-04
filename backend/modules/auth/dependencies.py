import uuid
from dataclasses import dataclass
from typing import Annotated
import jwt
from fastapi import Cookie, Depends, HTTPException, status
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database import get_session
from modules.users.models import User
from modules.users.schemas import RoleChoicesSchema, AccountStatusSchema
from .services import auth_service

ACCESS_TOKEN_COOKIE = "access_token"


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    platform_role: RoleChoicesSchema
    status: AccountStatusSchema


async def get_access_token_from_cookie(
    access_token: str | None = Cookie(None, alias=ACCESS_TOKEN_COOKIE),
) -> str:
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token missing"
        )
    return access_token



async def get_current_user(
    access_token: Annotated[str, Depends(get_access_token_from_cookie)],
    db: AsyncSession = Depends(get_session),
) -> CurrentUser:
    try:
        payload = auth_service.verify_access_token(access_token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token"
            )
        user_uuid = uuid.UUID(user_id)
        result = await db.execute(select(User).where(User.id == user_uuid))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token"
            )

        user_status = AccountStatusSchema(user.account_status)
        if user_status == AccountStatusSchema.INACTIVE and not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is pending verification"
            )
        elif user_status == AccountStatusSchema.LOCKED:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is locked"
            )

        return CurrentUser(
            user_id=user_uuid,
            platform_role=RoleChoicesSchema(user.role),
            status=user_status,
        )
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token"
        )


async def get_active_current_user(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CurrentUser:
    if current_user.status != AccountStatusSchema.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account setup or activation required"
        )
    return current_user


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
ActiveCurrentUserDep = Annotated[CurrentUser, Depends(get_active_current_user)]
