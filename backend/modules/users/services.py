import uuid
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from .models import User
from .schemas import UserCreateSchema


class UserService:
    async def get_by_email(self, db: AsyncSession, email: str) -> User | None:
        statement = select(User).where(User.email == email)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_id(self, db: AsyncSession, user_id: uuid.UUID) -> User | None:
        statement = select(User).where(User.id == user_id)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def create_user(
        self,
        db: AsyncSession,
        user_in: UserCreateSchema,
        hashed_password: str,
        security_answer_hash: str,
    ) -> User:
        db_user = User.model_validate(
            user_in,
            update={
                "hashed_password": hashed_password,
                "security_answer_hash": security_answer_hash,
                "is_active": False,  # Pending OTP verification
                "is_superuser": False,  # Default to False
            }
        )
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user


user_service = UserService()
