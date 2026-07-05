import uuid
import random
import calendar
from datetime import date, datetime, timezone
from decimal import Decimal
from fastapi import HTTPException, status
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.customer_profiles.models import CustomerProfile
from modules.customer_profiles.enums import KycStatusEnum
from modules.products.models import AccountProduct
from modules.products.services import product_service
from .models import BankAccount, InternalAccount
from .enums import AccountCurrencyEnum, AccountStatusEnum, AccountTypeEnum, InternalAccountTypeEnum
from .schemas import BankAccountCreateSchema, BankAccountUpdateSchema


class BankAccountService:
    async def list_customer_accounts(self, db: AsyncSession, user_id: uuid.UUID) -> list[BankAccount]:
        statement = select(BankAccount).where(BankAccount.user_id == user_id)
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_customer_account(self, db: AsyncSession, account_id: uuid.UUID, user_id: uuid.UUID) -> BankAccount:
        statement = select(BankAccount).where(BankAccount.id == account_id).where(BankAccount.user_id == user_id)
        result = await db.execute(statement)
        account = result.scalar_one_or_none()
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bank account not found"
            )
        return account

    async def list_all_accounts(
        self, db: AsyncSession, account_status: AccountStatusEnum | None = None, limit: int = 50, offset: int = 0
    ) -> list[BankAccount]:
        statement = select(BankAccount)
        if account_status:
            statement = statement.where(BankAccount.account_status == account_status)
        statement = statement.offset(offset).limit(limit)
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_account_by_id_for_admin(self, db: AsyncSession, account_id: uuid.UUID) -> BankAccount:
        statement = select(BankAccount).where(BankAccount.id == account_id)
        result = await db.execute(statement)
        account = result.scalar_one_or_none()
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bank account not found"
            )
        return account

    async def create_bank_account(self, db: AsyncSession, schema: BankAccountCreateSchema) -> BankAccount:
        # Check if user's KYC customer profile is approved
        statement = select(CustomerProfile).where(CustomerProfile.user_id == schema.user_id)
        result = await db.execute(statement)
        profile = result.scalar_one_or_none()
        if not profile or profile.kyc_status != KycStatusEnum.APPROVED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only approved KYC customers can open bank accounts"
            )

        # Atomic primary accounts reset
        if schema.is_primary:
            await self._reset_primary_accounts(db, schema.user_id)

        # Generate unique 10-digit account number string
        account_number = await self._generate_unique_account_number(db)
        product = await product_service.get_active_product_for_account_opening(
            db, schema.product_id
        )
        opened_at = datetime.now(timezone.utc).replace(tzinfo=None)

        account = BankAccount(
            user_id=schema.user_id,
            product_id=product.id,
            account_number=account_number,
            account_name=schema.account_name,
            account_type=product.account_type,
            currency=product.currency,
            account_status=AccountStatusEnum.ACTIVE,  # Default to ACTIVE when created by admin
            opened_at=opened_at,
            is_primary=schema.is_primary,
            interest_rate=product.interest_rate,
            minimum_balance=product.minimum_balance,
            monthly_fee=product.monthly_fee,
            fixed_deposit_term_months=product.fixed_deposit_term_months,
            fixed_deposit_maturity_date=self._calculate_fixed_deposit_maturity_date(
                product, opened_at.date()
            ),
            early_withdrawal_penalty_rate=product.early_withdrawal_penalty_rate,
        )

        db.add(account)
        await db.commit()
        await db.refresh(account)
        return account

    async def update_bank_account(self, db: AsyncSession, account_id: uuid.UUID, schema: BankAccountUpdateSchema) -> BankAccount:
        account = await self.get_account_by_id_for_admin(db, account_id)

        # If transitioning to CLOSED, ensure it wasn't already CLOSED
        if schema.account_status == AccountStatusEnum.CLOSED:
            if account.account_status == AccountStatusEnum.CLOSED:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Account is already closed"
                )
            account.closed_at = datetime.now(timezone.utc).replace(tzinfo=None)

        # If transitioning to ACTIVE from PENDING, set opened_at
        if schema.account_status == AccountStatusEnum.ACTIVE and account.account_status == AccountStatusEnum.PENDING:
            account.opened_at = datetime.now(timezone.utc).replace(tzinfo=None)

        # Cannot modify status of a CLOSED account
        if account.account_status == AccountStatusEnum.CLOSED and schema.account_status is not None and schema.account_status != AccountStatusEnum.CLOSED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot change status of a closed account"
            )

        # Atomic primary accounts reset
        if schema.is_primary is True and not account.is_primary:
            await self._reset_primary_accounts(db, account.user_id)

        update_data = schema.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(account, key, value)

        account.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.add(account)
        await db.commit()
        await db.refresh(account)
        return account

    async def freeze_account(self, db: AsyncSession, account_id: uuid.UUID) -> BankAccount:
        account = await self.get_account_by_id_for_admin(db, account_id)
        if account.account_status == AccountStatusEnum.CLOSED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot freeze a closed account"
            )
        account.account_status = AccountStatusEnum.FROZEN
        account.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.add(account)
        await db.commit()
        await db.refresh(account)
        return account

    async def close_account(self, db: AsyncSession, account_id: uuid.UUID) -> BankAccount:
        account = await self.get_account_by_id_for_admin(db, account_id)
        if account.account_status == AccountStatusEnum.CLOSED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Account is already closed"
            )
        account.account_status = AccountStatusEnum.CLOSED
        account.closed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        account.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.add(account)
        await db.commit()
        await db.refresh(account)
        return account

    async def _reset_primary_accounts(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        statement = select(BankAccount).where(BankAccount.user_id == user_id).where(BankAccount.is_primary == True)
        result = await db.execute(statement)
        primary_accounts = result.scalars().all()
        for primary_acc in primary_accounts:
            primary_acc.is_primary = False
            primary_acc.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.add(primary_acc)

    async def _generate_unique_account_number(self, db: AsyncSession) -> str:
        for _ in range(10):
            num = "".join([str(random.randint(0, 9)) for _ in range(10)])
            statement = select(BankAccount).where(BankAccount.account_number == num)
            res = await db.execute(statement)
            if not res.scalar_one_or_none():
                return num
        raise RuntimeError("Failed to generate unique account number")

    def _calculate_fixed_deposit_maturity_date(
        self, product: AccountProduct, opened_on: date
    ) -> date | None:
        if product.account_type != AccountTypeEnum.FIXED_DEPOSIT:
            return None

        if product.fixed_deposit_term_months is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Fixed deposit product is missing fixed_deposit_term_months",
            )

        month_index = opened_on.month - 1 + product.fixed_deposit_term_months
        year = opened_on.year + month_index // 12
        month = month_index % 12 + 1
        day = min(opened_on.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)


bank_account_service = BankAccountService()


class InternalAccountService:
    async def get_or_create_cash_settlement_account(
        self, db: AsyncSession, currency: AccountCurrencyEnum
    ) -> InternalAccount:
        account_code = f"CASH-{currency.value}"
        statement = (
            select(InternalAccount)
            .where(InternalAccount.account_code == account_code)
            .with_for_update()
        )
        result = await db.execute(statement)
        account = result.scalar_one_or_none()
        if account:
            return account

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        account = InternalAccount(
            account_code=account_code,
            account_name=f"Cash Settlement {currency.value}",
            account_type=InternalAccountTypeEnum.CASH_SETTLEMENT,
            currency=currency,
            balance=Decimal("0.00"),
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db.add(account)
        await db.flush()
        return account

    async def get_or_create_fee_income_account(
        self, db: AsyncSession, currency: AccountCurrencyEnum
    ) -> InternalAccount:
        account_code = f"FEE-INCOME-{currency.value}"
        statement = (
            select(InternalAccount)
            .where(InternalAccount.account_code == account_code)
            .with_for_update()
        )
        result = await db.execute(statement)
        account = result.scalar_one_or_none()
        if account:
            return account

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        account = InternalAccount(
            account_code=account_code,
            account_name=f"Fee Income {currency.value}",
            account_type=InternalAccountTypeEnum.FEE_INCOME,
            currency=currency,
            balance=Decimal("0.00"),
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db.add(account)
        await db.flush()
        return account

    async def get_or_create_interest_expense_account(
        self, db: AsyncSession, currency: AccountCurrencyEnum
    ) -> InternalAccount:
        account_code = f"INTEREST-EXPENSE-{currency.value}"
        statement = (
            select(InternalAccount)
            .where(InternalAccount.account_code == account_code)
            .with_for_update()
        )
        result = await db.execute(statement)
        account = result.scalar_one_or_none()
        if account:
            return account

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        account = InternalAccount(
            account_code=account_code,
            account_name=f"Interest Expense {currency.value}",
            account_type=InternalAccountTypeEnum.INTEREST_EXPENSE,
            currency=currency,
            balance=Decimal("0.00"),
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db.add(account)
        await db.flush()
        return account

    async def list_internal_accounts(
        self, db: AsyncSession, limit: int = 50, offset: int = 0
    ) -> list[InternalAccount]:
        statement = (
            select(InternalAccount)
            .order_by(InternalAccount.account_code)
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_internal_account_by_id(
        self, db: AsyncSession, account_id: uuid.UUID
    ) -> InternalAccount:
        statement = select(InternalAccount).where(InternalAccount.id == account_id)
        result = await db.execute(statement)
        account = result.scalar_one_or_none()
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Internal account not found",
            )
        return account


internal_account_service = InternalAccountService()
