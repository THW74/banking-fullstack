import uuid
from datetime import datetime, timezone
from fastapi import HTTPException, status
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from .models import NextOfKin
from .schemas import NextOfKinCreateSchema, NextOfKinUpdateSchema


class NextOfKinService:
    async def list_next_of_kin(self, db: AsyncSession, user_id: uuid.UUID) -> list[NextOfKin]:
        statement = select(NextOfKin).where(NextOfKin.user_id == user_id)
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_next_of_kin(self, db: AsyncSession, kin_id: uuid.UUID, user_id: uuid.UUID) -> NextOfKin:
        statement = select(NextOfKin).where(NextOfKin.id == kin_id).where(NextOfKin.user_id == user_id)
        result = await db.execute(statement)
        kin = result.scalar_one_or_none()
        if not kin:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Next of kin contact not found"
            )
        return kin

    async def create_next_of_kin(self, db: AsyncSession, user_id: uuid.UUID, schema: NextOfKinCreateSchema) -> NextOfKin:
        # Atomic primary kin handling
        if schema.is_primary:
            await self._reset_primary_kin(db, user_id)

        kin = NextOfKin(
            user_id=user_id,
            full_name=schema.full_name,
            relationship=schema.relationship,
            email=schema.email,
            phone_number=schema.phone_number,
            address=schema.address,
            city=schema.city,
            country=schema.country,
            nationality=schema.nationality,
            id_number=schema.id_number,
            passport_number=schema.passport_number,
            is_primary=schema.is_primary,
        )
        db.add(kin)
        await db.commit()
        await db.refresh(kin)
        return kin

    async def update_next_of_kin(self, db: AsyncSession, kin_id: uuid.UUID, user_id: uuid.UUID, schema: NextOfKinUpdateSchema) -> NextOfKin:
        kin = await self.get_next_of_kin(db, kin_id, user_id)

        # Atomic primary kin handling
        if schema.is_primary is True and not kin.is_primary:
            await self._reset_primary_kin(db, user_id)

        update_data = schema.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(kin, key, value)

        kin.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.add(kin)
        await db.commit()
        await db.refresh(kin)
        return kin

    async def delete_next_of_kin(self, db: AsyncSession, kin_id: uuid.UUID, user_id: uuid.UUID) -> None:
        kin = await self.get_next_of_kin(db, kin_id, user_id)
        await db.delete(kin)
        await db.commit()

    async def set_primary_next_of_kin(self, db: AsyncSession, kin_id: uuid.UUID, user_id: uuid.UUID) -> NextOfKin:
        kin = await self.get_next_of_kin(db, kin_id, user_id)
        if not kin.is_primary:
            await self._reset_primary_kin(db, user_id)
            kin.is_primary = True
            kin.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add(kin)
            await db.commit()
            await db.refresh(kin)
        return kin

    async def _reset_primary_kin(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        statement = select(NextOfKin).where(NextOfKin.user_id == user_id).where(NextOfKin.is_primary == True)
        result = await db.execute(statement)
        primary_kins = result.scalars().all()
        for primary_kin in primary_kins:
            primary_kin.is_primary = False
            primary_kin.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add(primary_kin)


next_of_kin_service = NextOfKinService()
