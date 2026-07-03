from sqlmodel import SQLModel, Session
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession
from .config import settings
# TODO: Import your models here to register them with SQLModel.metadata
# from modules.users.models import User
# from modules.auth.models import RefreshToken
from typing import Annotated, AsyncGenerator
from fastapi import Depends

engine: AsyncEngine = create_async_engine(settings.DATABASE_URL, echo=True)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSession(engine) as session:
        yield session

AsyncSessionDep = Annotated[AsyncSession, Depends(get_session)]
