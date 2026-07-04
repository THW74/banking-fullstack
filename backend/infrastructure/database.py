from sqlmodel import SQLModel, Session
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession
from .config import settings
# Import your models here to register them with SQLModel.metadata
from modules.users.models import User
from modules.customer_profiles.models import CustomerProfile
from modules.next_of_kin.models import NextOfKin
from modules.accounts.models import BankAccount, InternalAccount
from modules.transactions.models import Transaction, LedgerEntry
from typing import Annotated, AsyncGenerator, cast
from fastapi import Depends

engine: AsyncEngine = create_async_engine(cast(str, settings.DATABASE_URL), echo=True)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSession(engine) as session:
        yield session

AsyncSessionDep = Annotated[AsyncSession, Depends(get_session)]
