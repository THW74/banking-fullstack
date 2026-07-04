from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database import get_session
from modules.auth.dependencies import ActiveCurrentUserDep
from .schemas import UserReadSchema
from .services import user_service

router = APIRouter()


@router.get("/me", response_model=UserReadSchema)
async def get_me(
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session)
):
    user = await user_service.get_by_id(db, current_user.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user
