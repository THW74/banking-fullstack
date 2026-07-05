import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from modules.accounts.enums import AccountCurrencyEnum, AccountTypeEnum
from .enums import ProductStatusEnum
from .models import AccountProduct
from .schemas import ProductCreateSchema, ProductUpdateSchema


class ProductService:
    async def list_products(
        self,
        db: AsyncSession,
        status_filter: ProductStatusEnum | None = None,
        account_type_filter: AccountTypeEnum | None = None,
        currency_filter: AccountCurrencyEnum | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AccountProduct]:
        statement = select(AccountProduct)
        if status_filter:
            statement = statement.where(AccountProduct.status == status_filter)
        if account_type_filter:
            statement = statement.where(
                AccountProduct.account_type == account_type_filter
            )
        if currency_filter:
            statement = statement.where(AccountProduct.currency == currency_filter)
        statement = statement.offset(offset).limit(limit)
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_product_by_id(
        self, db: AsyncSession, product_id: uuid.UUID
    ) -> AccountProduct:
        statement = select(AccountProduct).where(AccountProduct.id == product_id)
        result = await db.execute(statement)
        product = result.scalar_one_or_none()
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account product not found",
            )
        return product

    async def get_active_product_for_account_opening(
        self, db: AsyncSession, product_id: uuid.UUID
    ) -> AccountProduct:
        product = await self.get_product_by_id(db, product_id)
        if product.status != ProductStatusEnum.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Account product is not open for new accounts",
            )
        return product

    async def create_product(
        self, db: AsyncSession, schema: ProductCreateSchema
    ) -> AccountProduct:
        product = AccountProduct(
            code=schema.code,
            name=schema.name,
            description=schema.description,
            account_type=schema.account_type,
            currency=schema.currency,
            status=ProductStatusEnum.DRAFT,
            interest_rate=schema.interest_rate,
            minimum_opening_deposit=schema.minimum_opening_deposit,
            minimum_balance=schema.minimum_balance,
            monthly_fee=schema.monthly_fee,
            fixed_deposit_term_months=schema.fixed_deposit_term_months,
            early_withdrawal_penalty_rate=schema.early_withdrawal_penalty_rate,
        )
        db.add(product)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A product with this code already exists",
            )
        await db.refresh(product)
        return product

    async def update_product(
        self, db: AsyncSession, product_id: uuid.UUID, schema: ProductUpdateSchema
    ) -> AccountProduct:
        product = await self.get_product_by_id(db, product_id)
        for field, value in schema.model_dump(exclude_unset=True).items():
            setattr(product, field, value)
        product.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.add(product)
        await db.commit()
        await db.refresh(product)
        return product

    async def activate_product(
        self, db: AsyncSession, product_id: uuid.UUID
    ) -> AccountProduct:
        product = await self.get_product_by_id(db, product_id)
        if product.status == ProductStatusEnum.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Product is already active",
            )
        if product.status == ProductStatusEnum.RETIRED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Retired products cannot be activated",
            )
        product.status = ProductStatusEnum.ACTIVE
        product.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.add(product)
        await db.commit()
        await db.refresh(product)
        return product

    async def retire_product(
        self, db: AsyncSession, product_id: uuid.UUID
    ) -> AccountProduct:
        product = await self.get_product_by_id(db, product_id)
        if product.status == ProductStatusEnum.RETIRED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Product is already retired",
            )
        product.status = ProductStatusEnum.RETIRED
        product.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.add(product)
        await db.commit()
        await db.refresh(product)
        return product


product_service = ProductService()
