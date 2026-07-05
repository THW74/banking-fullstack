import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from modules.accounts.enums import AccountCurrencyEnum
from modules.accounts.models import BankAccount, InternalAccount
from modules.transactions.enums import LedgerEntryTypeEnum, TransactionTypeEnum
from modules.transactions.models import LedgerEntry, Transaction
from .schemas import (
    AccountTargetType,
    GeneralLedgerEntrySchema,
    GeneralLedgerReportSchema,
    TrialBalanceLineSchema,
    TrialBalanceReportSchema,
)

CENT = Decimal("0.01")


@dataclass
class _TrialBalanceAccumulator:
    account_target_type: str
    account_id: uuid.UUID
    currency: AccountCurrencyEnum
    debit_total: Decimal = field(default_factory=lambda: Decimal("0.00"))
    credit_total: Decimal = field(default_factory=lambda: Decimal("0.00"))
    last_posted_at: datetime | None = None


class ReportService:
    async def get_trial_balance(
        self,
        db: AsyncSession,
        currency: AccountCurrencyEnum,
        as_of: date | None = None,
    ) -> TrialBalanceReportSchema:
        report_date = as_of or datetime.now(timezone.utc).date()
        cutoff = datetime.combine(report_date + timedelta(days=1), time.min)

        accounting_date = func.coalesce(Transaction.posted_at, LedgerEntry.created_at)
        statement = (
            select(LedgerEntry, Transaction)
            .join(Transaction, col(LedgerEntry.transaction_id) == col(Transaction.id))
            .where(LedgerEntry.currency == currency)
            .where(accounting_date < cutoff)
        )
        result = await db.execute(statement)

        accumulators: dict[tuple[str, uuid.UUID], _TrialBalanceAccumulator] = {}
        total_debit = Decimal("0.00")
        total_credit = Decimal("0.00")

        for ledger_entry, transaction in result.all():
            target_type, account_id = self._get_ledger_target(ledger_entry)
            key = (target_type, account_id)
            accumulator = accumulators.setdefault(
                key,
                _TrialBalanceAccumulator(
                    account_target_type=target_type,
                    account_id=account_id,
                    currency=ledger_entry.currency,
                ),
            )

            amount = self._normalize_amount(ledger_entry.amount)
            if ledger_entry.entry_type == LedgerEntryTypeEnum.DEBIT:
                accumulator.debit_total += amount
                total_debit += amount
            else:
                accumulator.credit_total += amount
                total_credit += amount

            posted_at = transaction.posted_at or ledger_entry.created_at
            if (
                accumulator.last_posted_at is None
                or posted_at > accumulator.last_posted_at
            ):
                accumulator.last_posted_at = posted_at

        customer_accounts = await self._get_customer_accounts(
            db,
            [
                account_id
                for target_type, account_id in accumulators
                if target_type == "customer_account"
            ],
        )
        internal_accounts = await self._get_internal_accounts(
            db,
            [
                account_id
                for target_type, account_id in accumulators
                if target_type == "internal_account"
            ],
        )

        lines: list[TrialBalanceLineSchema] = []
        total_net_debit = Decimal("0.00")
        total_net_credit = Decimal("0.00")

        for key in sorted(accumulators):
            accumulator = accumulators[key]
            net = self._normalize_amount(
                accumulator.debit_total - accumulator.credit_total
            )
            if net == Decimal("0.00"):
                continue

            if net > Decimal("0.00"):
                net_debit = net
                net_credit = Decimal("0.00")
                total_net_debit += net_debit
            else:
                net_debit = Decimal("0.00")
                net_credit = -net
                total_net_credit += net_credit

            line = self._build_line(
                accumulator,
                customer_accounts,
                internal_accounts,
                net_debit,
                net_credit,
            )
            lines.append(line)

        total_debit = self._normalize_amount(total_debit)
        total_credit = self._normalize_amount(total_credit)
        total_net_debit = self._normalize_amount(total_net_debit)
        total_net_credit = self._normalize_amount(total_net_credit)

        return TrialBalanceReportSchema(
            as_of=report_date,
            currency=currency,
            generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            total_debit=total_debit,
            total_credit=total_credit,
            total_net_debit=total_net_debit,
            total_net_credit=total_net_credit,
            is_balanced=(
                total_debit == total_credit and total_net_debit == total_net_credit
            ),
            line_count=len(lines),
            lines=lines,
        )

    async def get_general_ledger(
        self,
        db: AsyncSession,
        currency: AccountCurrencyEnum,
        from_date: date,
        to_date: date,
        account_target_type: AccountTargetType | None = None,
        account_id: uuid.UUID | None = None,
        account_code: str | None = None,
        transaction_type: TransactionTypeEnum | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> GeneralLedgerReportSchema:
        if from_date > to_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="from_date must be before or equal to to_date",
            )

        if account_id is not None and account_target_type is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="account_target_type is required when account_id is provided",
            )

        start_at = datetime.combine(from_date, time.min)
        end_at = datetime.combine(to_date + timedelta(days=1), time.min)
        accounting_date = func.coalesce(Transaction.posted_at, LedgerEntry.created_at)

        statement = (
            select(LedgerEntry, Transaction)
            .join(Transaction, col(LedgerEntry.transaction_id) == col(Transaction.id))
            .outerjoin(
                BankAccount,
                col(LedgerEntry.customer_account_id) == col(BankAccount.id),
            )
            .outerjoin(
                InternalAccount,
                col(LedgerEntry.internal_account_id) == col(InternalAccount.id),
            )
            .where(LedgerEntry.currency == currency)
            .where(accounting_date >= start_at)
            .where(accounting_date < end_at)
        )

        if transaction_type is not None:
            statement = statement.where(Transaction.transaction_type == transaction_type)

        if account_target_type == "customer_account":
            statement = statement.where(col(LedgerEntry.customer_account_id).is_not(None))
            if account_id is not None:
                statement = statement.where(LedgerEntry.customer_account_id == account_id)
            if account_code is not None:
                statement = statement.where(BankAccount.account_number == account_code)
        elif account_target_type == "internal_account":
            statement = statement.where(col(LedgerEntry.internal_account_id).is_not(None))
            if account_id is not None:
                statement = statement.where(LedgerEntry.internal_account_id == account_id)
            if account_code is not None:
                statement = statement.where(InternalAccount.account_code == account_code)
        elif account_code is not None:
            statement = statement.where(
                or_(
                    col(BankAccount.account_number) == account_code,
                    col(InternalAccount.account_code) == account_code,
                )
            )

        statement = (
            statement.order_by(
                accounting_date.asc(),
                col(LedgerEntry.created_at).asc(),
                col(LedgerEntry.id).asc(),
            )
            .offset(offset)
            .limit(limit + 1)
        )

        result = await db.execute(statement)
        rows = result.all()
        page_rows = rows[:limit]
        has_more = len(rows) > limit

        customer_account_ids: list[uuid.UUID] = []
        internal_account_ids: list[uuid.UUID] = []
        for ledger_entry, _transaction in page_rows:
            target_type, target_id = self._get_ledger_target(ledger_entry)
            if target_type == "customer_account":
                customer_account_ids.append(target_id)
            else:
                internal_account_ids.append(target_id)

        customer_accounts = await self._get_customer_accounts(db, customer_account_ids)
        internal_accounts = await self._get_internal_accounts(db, internal_account_ids)

        entries: list[GeneralLedgerEntrySchema] = []
        total_debit = Decimal("0.00")
        total_credit = Decimal("0.00")

        for ledger_entry, transaction in page_rows:
            entry = self._build_general_ledger_entry(
                ledger_entry,
                transaction,
                customer_accounts,
                internal_accounts,
            )
            entries.append(entry)
            total_debit += entry.debit_amount
            total_credit += entry.credit_amount

        return GeneralLedgerReportSchema(
            from_date=from_date,
            to_date=to_date,
            currency=currency,
            generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            total_debit=self._normalize_amount(total_debit),
            total_credit=self._normalize_amount(total_credit),
            entry_count=len(entries),
            limit=limit,
            offset=offset,
            has_more=has_more,
            entries=entries,
        )

    def _get_ledger_target(
        self, ledger_entry: LedgerEntry
    ) -> tuple[AccountTargetType, uuid.UUID]:
        has_customer = ledger_entry.customer_account_id is not None
        has_internal = ledger_entry.internal_account_id is not None

        if has_customer == has_internal:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Ledger entry must reference exactly one account target",
            )

        if ledger_entry.customer_account_id is not None:
            return "customer_account", ledger_entry.customer_account_id

        if ledger_entry.internal_account_id is not None:
            return "internal_account", ledger_entry.internal_account_id

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ledger entry must reference exactly one account target",
        )

    async def _get_customer_accounts(
        self, db: AsyncSession, account_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, BankAccount]:
        if not account_ids:
            return {}
        result = await db.execute(
            select(BankAccount).where(col(BankAccount.id).in_(account_ids))
        )
        return {account.id: account for account in result.scalars().all()}

    async def _get_internal_accounts(
        self, db: AsyncSession, account_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, InternalAccount]:
        if not account_ids:
            return {}
        result = await db.execute(
            select(InternalAccount).where(col(InternalAccount.id).in_(account_ids))
        )
        return {account.id: account for account in result.scalars().all()}

    def _build_line(
        self,
        accumulator: _TrialBalanceAccumulator,
        customer_accounts: dict[uuid.UUID, BankAccount],
        internal_accounts: dict[uuid.UUID, InternalAccount],
        net_debit: Decimal,
        net_credit: Decimal,
    ) -> TrialBalanceLineSchema:
        if accumulator.last_posted_at is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Trial balance line is missing posting date",
            )

        if accumulator.account_target_type == "customer_account":
            account = customer_accounts.get(accumulator.account_id)
            if account is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Bank account metadata missing for trial balance line",
                )
            return TrialBalanceLineSchema(
                account_target_type="customer_account",
                account_id=account.id,
                account_code=account.account_number,
                account_name=account.account_name,
                account_type=account.account_type.value,
                currency=accumulator.currency,
                debit_total=self._normalize_amount(accumulator.debit_total),
                credit_total=self._normalize_amount(accumulator.credit_total),
                net_debit=net_debit,
                net_credit=net_credit,
                last_posted_at=accumulator.last_posted_at,
            )

        account = internal_accounts.get(accumulator.account_id)
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal account metadata missing for trial balance line",
            )
        return TrialBalanceLineSchema(
            account_target_type="internal_account",
            account_id=account.id,
            account_code=account.account_code,
            account_name=account.account_name,
            account_type=account.account_type.value,
            currency=accumulator.currency,
            debit_total=self._normalize_amount(accumulator.debit_total),
            credit_total=self._normalize_amount(accumulator.credit_total),
            net_debit=net_debit,
            net_credit=net_credit,
            last_posted_at=accumulator.last_posted_at,
        )

    def _build_general_ledger_entry(
        self,
        ledger_entry: LedgerEntry,
        transaction: Transaction,
        customer_accounts: dict[uuid.UUID, BankAccount],
        internal_accounts: dict[uuid.UUID, InternalAccount],
    ) -> GeneralLedgerEntrySchema:
        target_type, account_id = self._get_ledger_target(ledger_entry)
        account_code: str
        account_name: str
        account_type: str

        if target_type == "customer_account":
            account = customer_accounts.get(account_id)
            if account is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Bank account metadata missing for general ledger entry",
                )
            account_code = account.account_number
            account_name = account.account_name
            account_type = account.account_type.value
        else:
            account = internal_accounts.get(account_id)
            if account is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Internal account metadata missing for general ledger entry",
                )
            account_code = account.account_code
            account_name = account.account_name
            account_type = account.account_type.value

        amount = self._normalize_amount(ledger_entry.amount)
        if ledger_entry.entry_type == LedgerEntryTypeEnum.DEBIT:
            debit_amount = amount
            credit_amount = Decimal("0.00")
            signed_amount = amount
        else:
            debit_amount = Decimal("0.00")
            credit_amount = amount
            signed_amount = -amount

        accounting_date = transaction.posted_at or ledger_entry.created_at

        return GeneralLedgerEntrySchema(
            ledger_entry_id=ledger_entry.id,
            transaction_id=transaction.id,
            transaction_reference=transaction.reference,
            transaction_type=transaction.transaction_type,
            transaction_status=transaction.status,
            accounting_date=accounting_date,
            posted_at=transaction.posted_at,
            account_target_type=target_type,
            account_id=account_id,
            account_code=account_code,
            account_name=account_name,
            account_type=account_type,
            currency=ledger_entry.currency,
            entry_type=ledger_entry.entry_type,
            debit_amount=debit_amount,
            credit_amount=credit_amount,
            signed_amount=self._normalize_amount(signed_amount),
            description=transaction.description,
            created_by_user_id=transaction.created_by_user_id,
        )

    def _normalize_amount(self, amount: Decimal) -> Decimal:
        return amount.quantize(CENT)


report_service = ReportService()
