import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlmodel import select, col
from sqlalchemy.ext.asyncio import AsyncSession

from modules.accounts.models import BankAccount
from modules.accounts.enums import AccountStatusEnum
from .models import Transaction, LedgerEntry
from .enums import TransactionTypeEnum, TransactionStatusEnum, LedgerEntryTypeEnum
from .schemas import CustomerTransferSchema, AdminDepositSchema, AdminWithdrawalSchema


class TransactionService:
    """Service layer for posting transactions and managing ledger entries.

    Ledger convention (simplified bank-app logic):
        DEBIT  = money decreases from a customer account
        CREDIT = money increases to a customer account

    For transfers, total DEBIT amount must equal total CREDIT amount.
    For deposits/withdrawals, PR #6 uses single-sided ledger entries.
    TODO: Introduce internal settlement accounts for full double-entry accounting.
    """

    # ------------------------------------------------------------------ #
    #  Posting actions                                                     #
    # ------------------------------------------------------------------ #

    async def transfer_between_accounts(
        self,
        db: AsyncSession,
        actor_user_id: uuid.UUID,
        schema: CustomerTransferSchema,
    ) -> Transaction:
        """Transfer funds between two active accounts.

        The source account must belong to the actor. Both accounts must be
        ACTIVE and share the same currency.
        """
        if schema.source_account_id == schema.destination_account_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source and destination accounts cannot be the same",
            )

        # Fetch accounts with row-level locks to prevent concurrent balance races.
        # TODO: Evaluate row-level locking under high-concurrency load testing.
        source = await self._get_account_for_update(db, schema.source_account_id)
        destination = await self._get_account_for_update(db, schema.destination_account_id)

        # Ownership check
        if source.user_id != actor_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Source account does not belong to you",
            )

        # Status checks
        if source.account_status != AccountStatusEnum.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source account is not active",
            )
        if destination.account_status != AccountStatusEnum.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Destination account is not active",
            )

        # Currency check
        if source.currency != destination.currency:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Currency mismatch between source and destination accounts",
            )

        # Balance check
        if source.available_balance < schema.amount:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Insufficient funds",
            )

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        reference = await self._generate_unique_reference(db)

        # Update balances
        source.available_balance -= schema.amount
        source.current_balance -= schema.amount
        source.updated_at = now

        destination.available_balance += schema.amount
        destination.current_balance += schema.amount
        destination.updated_at = now

        # Create transaction
        transaction = Transaction(
            reference=reference,
            transaction_type=TransactionTypeEnum.TRANSFER,
            status=TransactionStatusEnum.POSTED,
            source_account_id=schema.source_account_id,
            destination_account_id=schema.destination_account_id,
            amount=schema.amount,
            currency=source.currency,
            description=schema.description,
            created_by_user_id=actor_user_id,
            posted_at=now,
        )

        # Create ledger entries (DEBIT on source, CREDIT on destination)
        debit_entry = LedgerEntry(
            transaction_id=transaction.id,
            account_id=source.id,
            entry_type=LedgerEntryTypeEnum.DEBIT,
            amount=schema.amount,
            currency=source.currency,
            balance_after=source.available_balance,
        )
        credit_entry = LedgerEntry(
            transaction_id=transaction.id,
            account_id=destination.id,
            entry_type=LedgerEntryTypeEnum.CREDIT,
            amount=schema.amount,
            currency=destination.currency,
            balance_after=destination.available_balance,
        )

        db.add(source)
        db.add(destination)
        db.add(transaction)
        await db.flush()  # Flush transaction row so FK on ledger_entries is satisfied
        db.add(debit_entry)
        db.add(credit_entry)
        await db.commit()
        await db.refresh(transaction)
        return transaction

    async def admin_deposit(
        self,
        db: AsyncSession,
        actor_user_id: uuid.UUID,
        schema: AdminDepositSchema,
    ) -> Transaction:
        """Admin/staff deposit into a customer account.

        Creates a single CREDIT ledger entry. No internal settlement account
        exists yet, so this is single-sided.
        TODO: Introduce settlement account for full double-entry.
        """
        destination = await self._get_account_for_update(db, schema.destination_account_id)

        if destination.account_status != AccountStatusEnum.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Destination account is not active",
            )

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        reference = await self._generate_unique_reference(db)

        # Update balance
        destination.available_balance += schema.amount
        destination.current_balance += schema.amount
        destination.updated_at = now

        # Create transaction
        transaction = Transaction(
            reference=reference,
            transaction_type=TransactionTypeEnum.DEPOSIT,
            status=TransactionStatusEnum.POSTED,
            source_account_id=None,
            destination_account_id=schema.destination_account_id,
            amount=schema.amount,
            currency=destination.currency,
            description=schema.description,
            created_by_user_id=actor_user_id,
            posted_at=now,
        )

        # Single CREDIT ledger entry
        credit_entry = LedgerEntry(
            transaction_id=transaction.id,
            account_id=destination.id,
            entry_type=LedgerEntryTypeEnum.CREDIT,
            amount=schema.amount,
            currency=destination.currency,
            balance_after=destination.available_balance,
        )

        db.add(destination)
        db.add(transaction)
        await db.flush()  # Flush transaction row so FK on ledger_entries is satisfied
        db.add(credit_entry)
        await db.commit()
        await db.refresh(transaction)
        return transaction

    async def admin_withdrawal(
        self,
        db: AsyncSession,
        actor_user_id: uuid.UUID,
        schema: AdminWithdrawalSchema,
    ) -> Transaction:
        """Admin/staff withdrawal from a customer account.

        Creates a single DEBIT ledger entry. No internal settlement account
        exists yet, so this is single-sided.
        TODO: Introduce settlement account for full double-entry.
        """
        source = await self._get_account_for_update(db, schema.source_account_id)

        if source.account_status != AccountStatusEnum.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source account is not active",
            )

        if source.available_balance < schema.amount:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Insufficient funds",
            )

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        reference = await self._generate_unique_reference(db)

        # Update balance
        source.available_balance -= schema.amount
        source.current_balance -= schema.amount
        source.updated_at = now

        # Create transaction
        transaction = Transaction(
            reference=reference,
            transaction_type=TransactionTypeEnum.WITHDRAWAL,
            status=TransactionStatusEnum.POSTED,
            source_account_id=schema.source_account_id,
            destination_account_id=None,
            amount=schema.amount,
            currency=source.currency,
            description=schema.description,
            created_by_user_id=actor_user_id,
            posted_at=now,
        )

        # Single DEBIT ledger entry
        debit_entry = LedgerEntry(
            transaction_id=transaction.id,
            account_id=source.id,
            entry_type=LedgerEntryTypeEnum.DEBIT,
            amount=schema.amount,
            currency=source.currency,
            balance_after=source.available_balance,
        )

        db.add(source)
        db.add(transaction)
        await db.flush()  # Flush transaction row so FK on ledger_entries is satisfied
        db.add(debit_entry)
        await db.commit()
        await db.refresh(transaction)
        return transaction

    # ------------------------------------------------------------------ #
    #  Read queries                                                        #
    # ------------------------------------------------------------------ #

    async def list_transactions_for_user(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> list[Transaction]:
        """List transactions where source or destination belongs to user's accounts."""
        # First, get all account IDs for this user
        acct_stmt = select(BankAccount.id).where(BankAccount.user_id == user_id)
        acct_result = await db.execute(acct_stmt)
        account_ids = list(acct_result.scalars().all())

        if not account_ids:
            return []

        statement = (
            select(Transaction)
            .where(
                col(Transaction.source_account_id).in_(account_ids)
                | col(Transaction.destination_account_id).in_(account_ids)
            )
            .order_by(Transaction.created_at.desc())  # type: ignore[union-attr]
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_transaction_for_user(
        self, db: AsyncSession, transaction_id: uuid.UUID, user_id: uuid.UUID
    ) -> Transaction:
        """Get a single transaction scoped to the user's accounts."""
        acct_stmt = select(BankAccount.id).where(BankAccount.user_id == user_id)
        acct_result = await db.execute(acct_stmt)
        account_ids = list(acct_result.scalars().all())

        statement = select(Transaction).where(
            Transaction.id == transaction_id,
            col(Transaction.source_account_id).in_(account_ids)
            | col(Transaction.destination_account_id).in_(account_ids),
        )
        result = await db.execute(statement)
        txn = result.scalar_one_or_none()
        if not txn:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction not found",
            )
        return txn

    async def list_all_transactions(
        self,
        db: AsyncSession,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Transaction]:
        """Admin: list all transactions with pagination."""
        statement = (
            select(Transaction)
            .order_by(Transaction.created_at.desc())  # type: ignore[union-attr]
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_transaction_by_id(
        self, db: AsyncSession, transaction_id: uuid.UUID
    ) -> Transaction:
        """Admin: get a single transaction by ID."""
        statement = select(Transaction).where(Transaction.id == transaction_id)
        result = await db.execute(statement)
        txn = result.scalar_one_or_none()
        if not txn:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction not found",
            )
        return txn

    async def get_ledger_entries_for_transaction(
        self, db: AsyncSession, transaction_id: uuid.UUID
    ) -> list[LedgerEntry]:
        """Get all ledger entries for a given transaction."""
        statement = select(LedgerEntry).where(
            LedgerEntry.transaction_id == transaction_id
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    async def _get_account_for_update(
        self, db: AsyncSession, account_id: uuid.UUID
    ) -> BankAccount:
        """Fetch a bank account with a row-level lock (SELECT ... FOR UPDATE)."""
        statement = (
            select(BankAccount)
            .where(BankAccount.id == account_id)
            .with_for_update()
        )
        result = await db.execute(statement)
        account = result.scalar_one_or_none()
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bank account not found",
            )
        return account

    async def _generate_unique_reference(self, db: AsyncSession) -> str:
        """Generate a unique transaction reference string."""
        for _ in range(10):
            ref = f"TXN-{uuid.uuid4().hex[:16].upper()}"
            statement = select(Transaction).where(Transaction.reference == ref)
            result = await db.execute(statement)
            if not result.scalar_one_or_none():
                return ref
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate unique transaction reference",
        )


transaction_service = TransactionService()
