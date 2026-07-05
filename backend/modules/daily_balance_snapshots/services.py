import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from modules.accounts.enums import AccountCurrencyEnum
from modules.accounts.models import BankAccount
from modules.transactions.enums import LedgerEntryTypeEnum
from modules.transactions.models import LedgerEntry, Transaction
from .models import DailyBalanceSnapshot

CENT = Decimal("0.01")


class DailyBalanceSnapshotService:
    async def generate_snapshots(
        self,
        db: AsyncSession,
        business_date: date,
        currency: AccountCurrencyEnum | None = None,
        account_id: uuid.UUID | None = None,
    ) -> list[DailyBalanceSnapshot]:
        start_at, end_at = self._business_day_window(business_date)
        accounts = await self._get_accounts_for_snapshot(
            db, start_at, end_at, currency, account_id
        )
        if not accounts:
            return []

        account_ids = [account.id for account in accounts]
        existing_snapshots = await self._get_existing_snapshots(
            db, business_date, account_ids
        )
        entries_by_account = await self._get_daily_entries_by_account(
            db, accounts, start_at, end_at
        )

        snapshots: list[DailyBalanceSnapshot] = []
        now = self._utc_now()
        for account in accounts:
            snapshot = await self._build_snapshot(
                db,
                account,
                business_date,
                start_at,
                end_at,
                entries_by_account.get(account.id, []),
                existing_snapshots.get((account.id, account.currency)),
                now,
            )
            db.add(snapshot)
            snapshots.append(snapshot)

        await db.commit()
        for snapshot in snapshots:
            await db.refresh(snapshot)
        return snapshots

    async def list_snapshots(
        self,
        db: AsyncSession,
        business_date: date | None = None,
        currency: AccountCurrencyEnum | None = None,
        account_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DailyBalanceSnapshot]:
        statement = select(DailyBalanceSnapshot)
        if business_date is not None:
            statement = statement.where(
                DailyBalanceSnapshot.business_date == business_date
            )
        if currency is not None:
            statement = statement.where(DailyBalanceSnapshot.currency == currency)
        if account_id is not None:
            statement = statement.where(DailyBalanceSnapshot.account_id == account_id)
        statement = (
            statement.order_by(
                col(DailyBalanceSnapshot.business_date).desc(),
                col(DailyBalanceSnapshot.currency),
                col(DailyBalanceSnapshot.account_id),
            )
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_snapshot(
        self, db: AsyncSession, snapshot_id: uuid.UUID
    ) -> DailyBalanceSnapshot:
        snapshot = await db.get(DailyBalanceSnapshot, snapshot_id)
        if snapshot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Daily balance snapshot not found",
            )
        return snapshot

    async def _get_accounts_for_snapshot(
        self,
        db: AsyncSession,
        start_at: datetime,
        end_at: datetime,
        currency: AccountCurrencyEnum | None,
        account_id: uuid.UUID | None,
    ) -> list[BankAccount]:
        opened_at = func.coalesce(BankAccount.opened_at, BankAccount.created_at)
        statement = select(BankAccount).where(opened_at < end_at)
        if account_id is not None:
            statement = statement.where(BankAccount.id == account_id)
        if currency is not None:
            statement = statement.where(BankAccount.currency == currency)
        statement = statement.order_by(
            col(BankAccount.currency), col(BankAccount.account_number)
        )
        result = await db.execute(statement)
        accounts = list(result.scalars().all())

        if account_id is not None and not accounts:
            account = await db.get(BankAccount, account_id)
            if account is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Bank account not found",
                )
            if currency is not None and account.currency != currency:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="currency does not match the bank account",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Bank account was not open for the snapshot date",
            )

        return accounts

    async def _get_existing_snapshots(
        self,
        db: AsyncSession,
        business_date: date,
        account_ids: list[uuid.UUID],
    ) -> dict[tuple[uuid.UUID, AccountCurrencyEnum], DailyBalanceSnapshot]:
        result = await db.execute(
            select(DailyBalanceSnapshot)
            .where(DailyBalanceSnapshot.business_date == business_date)
            .where(col(DailyBalanceSnapshot.account_id).in_(account_ids))
        )
        return {
            (snapshot.account_id, snapshot.currency): snapshot
            for snapshot in result.scalars().all()
        }

    async def _get_daily_entries_by_account(
        self,
        db: AsyncSession,
        accounts: list[BankAccount],
        start_at: datetime,
        end_at: datetime,
    ) -> dict[uuid.UUID, list[LedgerEntry]]:
        account_by_id = {account.id: account for account in accounts}
        accounting_date = func.coalesce(Transaction.posted_at, LedgerEntry.created_at)
        statement = (
            select(LedgerEntry, Transaction)
            .join(Transaction, col(LedgerEntry.transaction_id) == col(Transaction.id))
            .where(col(LedgerEntry.customer_account_id).in_(list(account_by_id)))
            .where(accounting_date >= start_at)
            .where(accounting_date < end_at)
            .order_by(
                accounting_date.asc(),
                col(LedgerEntry.created_at).asc(),
                col(LedgerEntry.id).asc(),
            )
        )
        result = await db.execute(statement)

        entries_by_account: dict[uuid.UUID, list[LedgerEntry]] = defaultdict(list)
        for ledger_entry, _transaction in result.all():
            if ledger_entry.customer_account_id is None:
                continue
            account = account_by_id.get(ledger_entry.customer_account_id)
            if account is None or ledger_entry.currency != account.currency:
                continue
            entries_by_account[ledger_entry.customer_account_id].append(ledger_entry)
        return entries_by_account

    async def _build_snapshot(
        self,
        db: AsyncSession,
        account: BankAccount,
        business_date: date,
        start_at: datetime,
        end_at: datetime,
        daily_entries: list[LedgerEntry],
        existing_snapshot: DailyBalanceSnapshot | None,
        now: datetime,
    ) -> DailyBalanceSnapshot:
        opening_balance, closing_balance = await self._get_snapshot_balances(
            db, account, start_at, end_at, daily_entries
        )
        debit_total, credit_total, transaction_count = self._get_daily_totals(
            daily_entries
        )

        snapshot = existing_snapshot or DailyBalanceSnapshot(
            account_id=account.id,
            business_date=business_date,
            currency=account.currency,
            created_at=now,
        )
        snapshot.opening_balance = opening_balance
        snapshot.closing_balance = closing_balance
        snapshot.available_balance = closing_balance
        snapshot.current_balance = closing_balance
        snapshot.debit_total = debit_total
        snapshot.credit_total = credit_total
        snapshot.transaction_count = transaction_count
        snapshot.updated_at = now
        return snapshot

    async def _get_snapshot_balances(
        self,
        db: AsyncSession,
        account: BankAccount,
        start_at: datetime,
        end_at: datetime,
        daily_entries: list[LedgerEntry],
    ) -> tuple[Decimal, Decimal]:
        if daily_entries:
            opening_balance = self._balance_before_entry(daily_entries[0])
            closing_balance = self._normalize_amount(daily_entries[-1].balance_after)
            return opening_balance, closing_balance

        empty_day_balance = await self._get_empty_day_balance(
            db, account, start_at, end_at
        )
        return empty_day_balance, empty_day_balance

    def _get_daily_totals(
        self, daily_entries: list[LedgerEntry]
    ) -> tuple[Decimal, Decimal, int]:
        debit_total = Decimal("0.00")
        credit_total = Decimal("0.00")
        transaction_ids: set[uuid.UUID] = set()

        for entry in daily_entries:
            amount = self._normalize_amount(entry.amount)
            if entry.entry_type == LedgerEntryTypeEnum.DEBIT:
                debit_total += amount
            else:
                credit_total += amount
            transaction_ids.add(entry.transaction_id)

        return (
            self._normalize_amount(debit_total),
            self._normalize_amount(credit_total),
            len(transaction_ids),
        )

    async def _get_empty_day_balance(
        self,
        db: AsyncSession,
        account: BankAccount,
        start_at: datetime,
        end_at: datetime,
    ) -> Decimal:
        previous_entry = await self._get_boundary_entry(
            db, account.id, account.currency, start_at, before_cutoff=True
        )
        if previous_entry is not None:
            return self._normalize_amount(previous_entry.balance_after)

        next_entry = await self._get_boundary_entry(
            db, account.id, account.currency, end_at, before_cutoff=False
        )
        if next_entry is not None:
            return self._balance_before_entry(next_entry)

        return self._normalize_amount(account.current_balance)

    async def _get_boundary_entry(
        self,
        db: AsyncSession,
        account_id: uuid.UUID,
        currency: AccountCurrencyEnum,
        cutoff: datetime,
        before_cutoff: bool,
    ) -> LedgerEntry | None:
        accounting_date = func.coalesce(Transaction.posted_at, LedgerEntry.created_at)
        statement = (
            select(LedgerEntry)
            .join(Transaction, col(LedgerEntry.transaction_id) == col(Transaction.id))
            .where(LedgerEntry.customer_account_id == account_id)
            .where(LedgerEntry.currency == currency)
        )
        if before_cutoff:
            statement = statement.where(accounting_date < cutoff).order_by(
                accounting_date.desc(),
                col(LedgerEntry.created_at).desc(),
                col(LedgerEntry.id).desc(),
            )
        else:
            statement = statement.where(accounting_date >= cutoff).order_by(
                accounting_date.asc(),
                col(LedgerEntry.created_at).asc(),
                col(LedgerEntry.id).asc(),
            )
        result = await db.execute(statement.limit(1))
        return result.scalar_one_or_none()

    def _balance_before_entry(self, entry: LedgerEntry) -> Decimal:
        amount = self._normalize_amount(entry.amount)
        balance_after = self._normalize_amount(entry.balance_after)
        if entry.entry_type == LedgerEntryTypeEnum.DEBIT:
            return self._normalize_amount(balance_after + amount)
        return self._normalize_amount(balance_after - amount)

    def _business_day_window(self, business_date: date) -> tuple[datetime, datetime]:
        start_at = datetime.combine(business_date, time.min)
        end_at = datetime.combine(business_date + timedelta(days=1), time.min)
        return start_at, end_at

    def _normalize_amount(self, amount: Decimal) -> Decimal:
        return amount.quantize(CENT)

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)


daily_balance_snapshot_service = DailyBalanceSnapshotService()
