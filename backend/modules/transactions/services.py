import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException, status
from sqlmodel import select, col
from sqlalchemy.ext.asyncio import AsyncSession

from modules.accounts.models import BankAccount, InternalAccount
from modules.accounts.enums import (
    AccountCurrencyEnum,
    AccountStatusEnum,
    InternalAccountTypeEnum,
)
from modules.accounts.services import internal_account_service
from .models import Transaction, LedgerEntry, FeeRule
from .enums import TransactionTypeEnum, TransactionStatusEnum, LedgerEntryTypeEnum
from .schemas import (
    CustomerTransferSchema,
    AdminDepositSchema,
    AdminInterestPostingSchema,
    AdminWithdrawalSchema,
    TransactionReversalSchema,
)


class FeeService:
    async def calculate_fee(
        self,
        db: AsyncSession,
        transaction_type: TransactionTypeEnum,
        currency: AccountCurrencyEnum,
        amount: Decimal,
    ) -> Decimal:
        statement = select(FeeRule).where(
            FeeRule.transaction_type == transaction_type,
            FeeRule.currency == currency,
            FeeRule.is_active == True,
        )
        result = await db.execute(statement)
        rules = list(result.scalars().all())

        if len(rules) > 1:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Multiple active fee rules found",
            )

        if not rules:
            return Decimal("0.00")

        rule = rules[0]
        fee = rule.fixed_amount + (amount * rule.percentage_rate)
        fee = max(fee, rule.min_fee)
        if rule.max_fee is not None:
            fee = min(fee, rule.max_fee)
        return fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


fee_service = FeeService()


class TransactionService:
    """Service layer for posting transactions and managing ledger entries.

    Ledger convention (simplified bank-app logic):
        DEBIT  = money decreases from a customer account
        CREDIT = money increases to a customer account

    Internal cash settlement entries are used to keep deposits and
    withdrawals balanced. Every posted transaction must have equal total
    DEBIT and CREDIT amounts.
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

        fee_amount = await fee_service.calculate_fee(
            db,
            TransactionTypeEnum.TRANSFER,
            source.currency,
            schema.amount,
        )
        total_debit_amount = schema.amount + fee_amount

        # Balance check
        if source.available_balance < total_debit_amount:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Insufficient funds including fee",
            )

        fee_account: InternalAccount | None = None
        if fee_amount > Decimal("0.00"):
            fee_account = await internal_account_service.get_or_create_fee_income_account(
                db, source.currency
            )

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        reference = await self._generate_unique_reference(db)

        # Update balances
        source.available_balance -= total_debit_amount
        source.current_balance -= total_debit_amount
        source.updated_at = now

        destination.available_balance += schema.amount
        destination.current_balance += schema.amount
        destination.updated_at = now

        if fee_account is not None:
            self._apply_internal_account_entry_effect(
                fee_account,
                LedgerEntryTypeEnum.CREDIT,
                fee_amount,
            )
            fee_account.updated_at = now

        # Create transaction
        transaction = Transaction(
            reference=reference,
            transaction_type=TransactionTypeEnum.TRANSFER,
            status=TransactionStatusEnum.POSTED,
            source_account_id=schema.source_account_id,
            destination_account_id=schema.destination_account_id,
            amount=schema.amount,
            fee_amount=fee_amount,
            total_debit_amount=total_debit_amount,
            currency=source.currency,
            description=schema.description,
            created_by_user_id=actor_user_id,
            posted_at=now,
        )

        # Create ledger entries (DEBIT on source, CREDIT on destination/fees)
        debit_entry = LedgerEntry(
            transaction_id=transaction.id,
            customer_account_id=source.id,
            entry_type=LedgerEntryTypeEnum.DEBIT,
            amount=total_debit_amount,
            currency=source.currency,
            balance_after=source.available_balance,
        )
        credit_entry = LedgerEntry(
            transaction_id=transaction.id,
            customer_account_id=destination.id,
            entry_type=LedgerEntryTypeEnum.CREDIT,
            amount=schema.amount,
            currency=destination.currency,
            balance_after=destination.available_balance,
        )
        entries = [debit_entry, credit_entry]
        if fee_account is not None:
            entries.append(
                LedgerEntry(
                    transaction_id=transaction.id,
                    internal_account_id=fee_account.id,
                    entry_type=LedgerEntryTypeEnum.CREDIT,
                    amount=fee_amount,
                    currency=source.currency,
                    balance_after=fee_account.balance,
                )
            )
        self._assert_ledger_entries_valid(entries)

        if fee_account is not None:
            db.add(fee_account)
        db.add(source)
        db.add(destination)
        db.add(transaction)
        await db.flush()  # Flush transaction row so FK on ledger_entries is satisfied
        for entry in entries:
            db.add(entry)
        await db.commit()
        await db.refresh(transaction)

        try:
            from modules.notifications.services import notification_service
            from modules.notifications.enums import NotificationTypeEnum
            
            # Notify sender
            await notification_service.create_notification(
                db,
                user_id=source.user_id,
                title="Transfer Sent",
                message=f"You have sent {transaction.amount} {transaction.currency} to account {destination.account_number}.",
                notification_type=NotificationTypeEnum.TRANSACTION,
                source_metadata={"transaction_id": str(transaction.id)},
            )
            
            # Notify receiver (if different customer)
            if destination.user_id != source.user_id:
                await notification_service.create_notification(
                    db,
                    user_id=destination.user_id,
                    title="Transfer Received",
                    message=f"You have received {transaction.amount} {transaction.currency} from account {source.account_number}.",
                    notification_type=NotificationTypeEnum.TRANSACTION,
                    source_metadata={"transaction_id": str(transaction.id)},
                )
        except Exception:
            await db.rollback()

        await db.refresh(transaction)
        return transaction

    async def admin_deposit(
        self,
        db: AsyncSession,
        actor_user_id: uuid.UUID,
        schema: AdminDepositSchema,
    ) -> Transaction:
        """Admin/staff deposit into a customer account.

        Creates a balanced internal cash DEBIT and customer CREDIT entry.
        """
        destination = await self._get_account_for_update(db, schema.destination_account_id)

        if destination.account_status != AccountStatusEnum.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Destination account is not active",
            )

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        reference = await self._generate_unique_reference(db)
        cash_account = (
            await internal_account_service.get_or_create_cash_settlement_account(
                db, destination.currency
            )
        )

        # Update balances
        self._apply_internal_account_entry_effect(
            cash_account,
            LedgerEntryTypeEnum.DEBIT,
            schema.amount,
        )
        cash_account.updated_at = now
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
            fee_amount=Decimal("0.00"),
            total_debit_amount=schema.amount,
            currency=destination.currency,
            description=schema.description,
            created_by_user_id=actor_user_id,
            posted_at=now,
        )

        # Balanced ledger entries: DEBIT internal cash, CREDIT customer account
        cash_entry = LedgerEntry(
            transaction_id=transaction.id,
            internal_account_id=cash_account.id,
            entry_type=LedgerEntryTypeEnum.DEBIT,
            amount=schema.amount,
            currency=destination.currency,
            balance_after=cash_account.balance,
        )
        credit_entry = LedgerEntry(
            transaction_id=transaction.id,
            customer_account_id=destination.id,
            entry_type=LedgerEntryTypeEnum.CREDIT,
            amount=schema.amount,
            currency=destination.currency,
            balance_after=destination.available_balance,
        )
        entries = [cash_entry, credit_entry]
        self._assert_ledger_entries_valid(entries)

        db.add(cash_account)
        db.add(destination)
        db.add(transaction)
        await db.flush()  # Flush transaction row so FK on ledger_entries is satisfied
        for entry in entries:
            db.add(entry)
        await db.commit()
        await db.refresh(transaction)

        try:
            from modules.notifications.services import notification_service
            from modules.notifications.enums import NotificationTypeEnum
            await notification_service.create_notification(
                db,
                user_id=destination.user_id,
                title="Deposit Posted",
                message=f"A deposit of {transaction.amount} {transaction.currency} has been posted to your account.",
                notification_type=NotificationTypeEnum.TRANSACTION,
                source_metadata={"transaction_id": str(transaction.id)},
            )
        except Exception:
            await db.rollback()

        await db.refresh(transaction)
        return transaction

    async def admin_interest_posting(
        self,
        db: AsyncSession,
        actor_user_id: uuid.UUID,
        schema: AdminInterestPostingSchema,
    ) -> Transaction:
        """Admin/staff post manual interest into a customer account.

        Creates a balanced internal interest expense DEBIT and customer CREDIT
        entry.
        """
        destination = await self._get_account_for_update(
            db, schema.destination_account_id
        )

        if destination.account_status != AccountStatusEnum.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Destination account is not active",
            )

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        reference = await self._generate_unique_reference(db)
        interest_expense_account = (
            await internal_account_service.get_or_create_interest_expense_account(
                db, destination.currency
            )
        )

        self._apply_internal_account_entry_effect(
            interest_expense_account,
            LedgerEntryTypeEnum.DEBIT,
            schema.amount,
        )
        interest_expense_account.updated_at = now
        destination.available_balance += schema.amount
        destination.current_balance += schema.amount
        destination.updated_at = now

        transaction = Transaction(
            reference=reference,
            transaction_type=TransactionTypeEnum.INTEREST_POSTING,
            status=TransactionStatusEnum.POSTED,
            source_account_id=None,
            destination_account_id=schema.destination_account_id,
            amount=schema.amount,
            fee_amount=Decimal("0.00"),
            total_debit_amount=schema.amount,
            currency=destination.currency,
            description=schema.description,
            created_by_user_id=actor_user_id,
            posted_at=now,
        )

        interest_expense_entry = LedgerEntry(
            transaction_id=transaction.id,
            internal_account_id=interest_expense_account.id,
            entry_type=LedgerEntryTypeEnum.DEBIT,
            amount=schema.amount,
            currency=destination.currency,
            balance_after=interest_expense_account.balance,
        )
        credit_entry = LedgerEntry(
            transaction_id=transaction.id,
            customer_account_id=destination.id,
            entry_type=LedgerEntryTypeEnum.CREDIT,
            amount=schema.amount,
            currency=destination.currency,
            balance_after=destination.available_balance,
        )
        entries = [interest_expense_entry, credit_entry]
        self._assert_ledger_entries_valid(entries)

        db.add(interest_expense_account)
        db.add(destination)
        db.add(transaction)
        await db.flush()
        for entry in entries:
            db.add(entry)
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

        Creates a balanced customer DEBIT and internal cash CREDIT entry.
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
        cash_account = (
            await internal_account_service.get_or_create_cash_settlement_account(
                db, source.currency
            )
        )

        # Update balances
        source.available_balance -= schema.amount
        source.current_balance -= schema.amount
        source.updated_at = now
        self._apply_internal_account_entry_effect(
            cash_account,
            LedgerEntryTypeEnum.CREDIT,
            schema.amount,
        )
        cash_account.updated_at = now

        # Create transaction
        transaction = Transaction(
            reference=reference,
            transaction_type=TransactionTypeEnum.WITHDRAWAL,
            status=TransactionStatusEnum.POSTED,
            source_account_id=schema.source_account_id,
            destination_account_id=None,
            amount=schema.amount,
            fee_amount=Decimal("0.00"),
            total_debit_amount=schema.amount,
            currency=source.currency,
            description=schema.description,
            created_by_user_id=actor_user_id,
            posted_at=now,
        )

        # Balanced ledger entries: DEBIT customer account, CREDIT internal cash
        debit_entry = LedgerEntry(
            transaction_id=transaction.id,
            customer_account_id=source.id,
            entry_type=LedgerEntryTypeEnum.DEBIT,
            amount=schema.amount,
            currency=source.currency,
            balance_after=source.available_balance,
        )
        cash_entry = LedgerEntry(
            transaction_id=transaction.id,
            internal_account_id=cash_account.id,
            entry_type=LedgerEntryTypeEnum.CREDIT,
            amount=schema.amount,
            currency=source.currency,
            balance_after=cash_account.balance,
        )
        entries = [debit_entry, cash_entry]
        self._assert_ledger_entries_valid(entries)

        db.add(cash_account)
        db.add(source)
        db.add(transaction)
        await db.flush()  # Flush transaction row so FK on ledger_entries is satisfied
        for entry in entries:
            db.add(entry)
        await db.commit()
        await db.refresh(transaction)

        try:
            from modules.notifications.services import notification_service
            from modules.notifications.enums import NotificationTypeEnum
            await notification_service.create_notification(
                db,
                user_id=source.user_id,
                title="Withdrawal Posted",
                message=f"A withdrawal of {transaction.amount} {transaction.currency} has been posted from your account.",
                notification_type=NotificationTypeEnum.TRANSACTION,
                source_metadata={"transaction_id": str(transaction.id)},
            )
        except Exception:
            await db.rollback()

        await db.refresh(transaction)
        return transaction

    async def reverse_transaction(
        self,
        db: AsyncSession,
        transaction_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        schema: TransactionReversalSchema,
    ) -> Transaction:
        """Reverse a posted transaction by creating opposite ledger entries."""
        original = await self._get_transaction_for_update(db, transaction_id)

        if original.transaction_type == TransactionTypeEnum.REVERSAL:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reversal transactions cannot be reversed",
            )

        if original.status != TransactionStatusEnum.POSTED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only posted transactions can be reversed",
            )

        if original.reversed_by_transaction_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Transaction is already reversed",
            )

        original_entries = await self.get_ledger_entries_for_transaction(
            db, original.id
        )
        if not original_entries:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Transaction has no ledger entries",
            )

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        reference = await self._generate_unique_reference(db)
        source_account_id, destination_account_id = (
            self._get_reversal_account_targets(original)
        )
        reversal_total_debit_amount = original.total_debit_amount
        if reversal_total_debit_amount == Decimal("0.00"):
            reversal_total_debit_amount = original.amount

        reversal_transaction = Transaction(
            reference=reference,
            transaction_type=TransactionTypeEnum.REVERSAL,
            status=TransactionStatusEnum.POSTED,
            source_account_id=source_account_id,
            destination_account_id=destination_account_id,
            amount=original.amount,
            fee_amount=original.fee_amount,
            total_debit_amount=reversal_total_debit_amount,
            currency=original.currency,
            description=schema.reason,
            created_by_user_id=actor_user_id,
            reversed_transaction_id=original.id,
            reversal_reason=schema.reason,
            posted_at=now,
        )

        reversal_entries: list[LedgerEntry] = []
        for original_entry in original_entries:
            if original_entry.customer_account_id is not None:
                reversal_entries.append(
                    await self._reverse_customer_ledger_entry(
                        db, original_entry, reversal_transaction.id, now
                    )
                )
                continue

            if original_entry.internal_account_id is not None:
                reversal_entries.append(
                    await self._reverse_internal_ledger_entry(
                        db, original_entry, reversal_transaction.id, now
                    )
                )
                continue

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Ledger entry must reference exactly one account target",
            )

        self._assert_ledger_entries_valid(reversal_entries)

        db.add(reversal_transaction)
        await db.flush()

        original.status = TransactionStatusEnum.REVERSED
        original.reversed_by_transaction_id = reversal_transaction.id
        original.reversal_reason = schema.reason
        original.reversed_at = now
        original.reversed_by_user_id = actor_user_id

        db.add(original)
        for entry in reversal_entries:
            db.add(entry)

        await db.commit()
        await db.refresh(reversal_transaction)

        try:
            from modules.notifications.services import notification_service
            from modules.notifications.enums import NotificationTypeEnum
            
            src_acct = None
            if original.source_account_id is not None:
                from modules.accounts.services import bank_account_service
                src_acct = await bank_account_service.get_account_by_id_for_admin(db, original.source_account_id)
                await notification_service.create_notification(
                    db,
                    user_id=src_acct.user_id,
                    title="Transaction Reversed",
                    message=f"Transaction {original.reference} of amount {original.amount} {original.currency} has been reversed.",
                    notification_type=NotificationTypeEnum.TRANSACTION,
                    source_metadata={"transaction_id": str(reversal_transaction.id), "reversed_transaction_id": str(original.id)},
                )
            
            if original.destination_account_id is not None:
                from modules.accounts.services import bank_account_service
                dest_acct = await bank_account_service.get_account_by_id_for_admin(db, original.destination_account_id)
                if src_acct is None or dest_acct.user_id != src_acct.user_id:
                    await notification_service.create_notification(
                        db,
                        user_id=dest_acct.user_id,
                        title="Transaction Reversed",
                        message=f"Transaction {original.reference} of amount {original.amount} {original.currency} has been reversed.",
                        notification_type=NotificationTypeEnum.TRANSACTION,
                        source_metadata={"transaction_id": str(reversal_transaction.id), "reversed_transaction_id": str(original.id)},
                    )
        except Exception:
            await db.rollback()

        await db.refresh(reversal_transaction)
        return reversal_transaction

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

    async def get_ledger_entries_for_transaction_user(
        self, db: AsyncSession, transaction_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[LedgerEntry]:
        transaction = await self.get_transaction_for_user(
            db, transaction_id, user_id
        )
        return await self.get_ledger_entries_for_transaction(db, transaction.id)

    async def get_ledger_entries_for_transaction_admin(
        self, db: AsyncSession, transaction_id: uuid.UUID
    ) -> list[LedgerEntry]:
        transaction = await self.get_transaction_by_id(db, transaction_id)
        return await self.get_ledger_entries_for_transaction(db, transaction.id)

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    async def _get_transaction_for_update(
        self, db: AsyncSession, transaction_id: uuid.UUID
    ) -> Transaction:
        statement = (
            select(Transaction)
            .where(Transaction.id == transaction_id)
            .with_for_update()
        )
        result = await db.execute(statement)
        transaction = result.scalar_one_or_none()
        if not transaction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction not found",
            )
        return transaction

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

    async def _get_internal_account_for_update(
        self, db: AsyncSession, internal_account_id: uuid.UUID
    ) -> InternalAccount:
        statement = (
            select(InternalAccount)
            .where(InternalAccount.id == internal_account_id)
            .with_for_update()
        )
        result = await db.execute(statement)
        account = result.scalar_one_or_none()
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Internal account not found",
            )
        return account

    def _get_reversal_account_targets(
        self, original: Transaction
    ) -> tuple[uuid.UUID | None, uuid.UUID | None]:
        if original.transaction_type == TransactionTypeEnum.DEPOSIT:
            return original.destination_account_id, None

        if original.transaction_type == TransactionTypeEnum.WITHDRAWAL:
            return None, original.source_account_id

        if original.transaction_type == TransactionTypeEnum.TRANSFER:
            return original.destination_account_id, original.source_account_id

        if original.transaction_type == TransactionTypeEnum.INTEREST_POSTING:
            return original.destination_account_id, None

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transaction type cannot be reversed",
        )

    async def _reverse_customer_ledger_entry(
        self,
        db: AsyncSession,
        original_entry: LedgerEntry,
        reversal_transaction_id: uuid.UUID,
        now: datetime,
    ) -> LedgerEntry:
        if original_entry.customer_account_id is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Ledger entry must reference exactly one account target",
            )

        account = await self._get_account_for_update(
            db, original_entry.customer_account_id
        )

        if original_entry.entry_type == LedgerEntryTypeEnum.DEBIT:
            account.available_balance += original_entry.amount
            account.current_balance += original_entry.amount
            reversal_type = LedgerEntryTypeEnum.CREDIT
        else:
            if account.available_balance < original_entry.amount:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Insufficient funds to reverse transaction",
                )
            account.available_balance -= original_entry.amount
            account.current_balance -= original_entry.amount
            reversal_type = LedgerEntryTypeEnum.DEBIT

        account.updated_at = now
        db.add(account)

        return LedgerEntry(
            transaction_id=reversal_transaction_id,
            customer_account_id=account.id,
            entry_type=reversal_type,
            amount=original_entry.amount,
            currency=original_entry.currency,
            balance_after=account.available_balance,
        )

    async def _reverse_internal_ledger_entry(
        self,
        db: AsyncSession,
        original_entry: LedgerEntry,
        reversal_transaction_id: uuid.UUID,
        now: datetime,
    ) -> LedgerEntry:
        if original_entry.internal_account_id is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Ledger entry must reference exactly one account target",
            )

        account = await self._get_internal_account_for_update(
            db, original_entry.internal_account_id
        )

        if original_entry.entry_type == LedgerEntryTypeEnum.DEBIT:
            reversal_type = LedgerEntryTypeEnum.CREDIT
        else:
            reversal_type = LedgerEntryTypeEnum.DEBIT

        self._apply_internal_account_entry_effect(
            account,
            reversal_type,
            original_entry.amount,
        )

        account.updated_at = now
        db.add(account)

        return LedgerEntry(
            transaction_id=reversal_transaction_id,
            internal_account_id=account.id,
            entry_type=reversal_type,
            amount=original_entry.amount,
            currency=original_entry.currency,
            balance_after=account.balance,
        )

    def _apply_internal_account_entry_effect(
        self,
        account: InternalAccount,
        entry_type: LedgerEntryTypeEnum,
        amount: Decimal,
    ) -> None:
        if account.account_type == InternalAccountTypeEnum.CASH_SETTLEMENT:
            if entry_type == LedgerEntryTypeEnum.DEBIT:
                account.balance += amount
            else:
                account.balance -= amount
            return

        if account.account_type == InternalAccountTypeEnum.FEE_INCOME:
            if entry_type == LedgerEntryTypeEnum.CREDIT:
                account.balance += amount
            else:
                account.balance -= amount
            return

        if account.account_type == InternalAccountTypeEnum.INTEREST_EXPENSE:
            if entry_type == LedgerEntryTypeEnum.DEBIT:
                account.balance += amount
            else:
                account.balance -= amount
            return

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unsupported internal account type",
        )

    def _assert_ledger_entries_valid(self, entries: list[LedgerEntry]) -> None:
        for entry in entries:
            self._assert_single_ledger_target(entry)
        self._assert_ledger_entries_balanced(entries)

    def _assert_single_ledger_target(self, entry: LedgerEntry) -> None:
        has_customer = entry.customer_account_id is not None
        has_internal = entry.internal_account_id is not None

        if has_customer == has_internal:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Ledger entry must reference exactly one account target",
            )

    def _assert_ledger_entries_balanced(self, entries: list[LedgerEntry]) -> None:
        total_debit = sum(
            (
                entry.amount
                for entry in entries
                if entry.entry_type == LedgerEntryTypeEnum.DEBIT
            ),
            Decimal("0.00"),
        )
        total_credit = sum(
            (
                entry.amount
                for entry in entries
                if entry.entry_type == LedgerEntryTypeEnum.CREDIT
            ),
            Decimal("0.00"),
        )

        if total_debit != total_credit:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Ledger entries are not balanced",
            )

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
