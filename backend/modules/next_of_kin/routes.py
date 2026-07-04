import uuid
from fastapi import APIRouter, Depends, status, Response
from sqlalchemy.ext.asyncio import AsyncSession
from infrastructure.database import get_session
from modules.auth.dependencies import ActiveCurrentUserDep
from .schemas import NextOfKinCreateSchema, NextOfKinUpdateSchema, NextOfKinReadSchema
from .services import next_of_kin_service

next_of_kin_router = APIRouter()


@next_of_kin_router.get(
    "",
    response_model=list[NextOfKinReadSchema],
    summary="List all next of kin contacts"
)
async def list_next_of_kin(
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session)
):
    return await next_of_kin_service.list_next_of_kin(db, current_user.user_id)


@next_of_kin_router.post(
    "",
    response_model=NextOfKinReadSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new next of kin contact"
)
async def create_next_of_kin(
    payload: NextOfKinCreateSchema,
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session)
):
    return await next_of_kin_service.create_next_of_kin(db, current_user.user_id, payload)


@next_of_kin_router.get(
    "/{kin_id}",
    response_model=NextOfKinReadSchema,
    summary="Get details of a next of kin contact"
)
async def get_next_of_kin(
    kin_id: uuid.UUID,
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session)
):
    return await next_of_kin_service.get_next_of_kin(db, kin_id, current_user.user_id)


@next_of_kin_router.patch(
    "/{kin_id}",
    response_model=NextOfKinReadSchema,
    summary="Update details of a next of kin contact"
)
async def update_next_of_kin(
    kin_id: uuid.UUID,
    payload: NextOfKinUpdateSchema,
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session)
):
    return await next_of_kin_service.update_next_of_kin(db, kin_id, current_user.user_id, payload)


@next_of_kin_router.delete(
    "/{kin_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a next of kin contact"
)
async def delete_next_of_kin(
    kin_id: uuid.UUID,
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session)
):
    await next_of_kin_service.delete_next_of_kin(db, kin_id, current_user.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@next_of_kin_router.post(
    "/{kin_id}/primary",
    response_model=NextOfKinReadSchema,
    summary="Set a next of kin contact as primary"
)
async def set_primary_next_of_kin(
    kin_id: uuid.UUID,
    current_user: ActiveCurrentUserDep,
    db: AsyncSession = Depends(get_session)
):
    return await next_of_kin_service.set_primary_next_of_kin(db, kin_id, current_user.user_id)
