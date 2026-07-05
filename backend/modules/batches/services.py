import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from modules.accounts.enums import AccountCurrencyEnum
from modules.transactions.enums import (
    LedgerEntryTypeEnum,
    TransactionStatusEnum,
)
from modules.transactions.models import LedgerEntry, Transaction
from .enums import EndOfDayBatchStatusEnum, EndOfDayValidationIssueTypeEnum
from .models import (
    EndOfDayBatch,
    EndOfDayBatchCurrencySummary,
    EndOfDayBatchValidationIssue,
)
from .schemas import (
    EndOfDayBatchCurrencySummaryReadSchema,
    EndOfDayBatchReadSchema,
    EndOfDayBatchValidationIssueReadSchema,
)

CENT = Decimal("0.01")


@dataclass
class _CurrencyAccumulator:
    currency: AccountCurrencyEnum
    transaction_ids: set[uuid.UUID] = field(default_factory=set)
    ledger_entry_count: int = 0
    total_debit: Decimal = field(default_factory=lambda: Decimal("0.00"))
    total_credit: Decimal = field(default_factory=lambda: Decimal("0.00"))


class EndOfDayBatchService:
    async def run_end_of_day_batch(
        self,
        db: AsyncSession,
        business_date: date,
        requested_by_user_id: uuid.UUID,
    ) -> EndOfDayBatchReadSchema:
        existing_batch = await self._get_batch_by_business_date_for_update(
            db, business_date
        )
        if existing_batch is not None:
            if existing_batch.status == EndOfDayBatchStatusEnum.COMPLETED:
                return await self._build_read_schema(db, existing_batch)
            if existing_batch.status == EndOfDayBatchStatusEnum.RUNNING:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="End-of-day batch is already running",
                )
            batch = existing_batch
            await self._clear_batch_results(db, batch.id)
        else:
            batch = EndOfDayBatch(
                business_date=business_date,
                requested_by_user_id=requested_by_user_id,
            )

        now = self._utc_now()
        batch.status = EndOfDayBatchStatusEnum.RUNNING
        batch.started_at = now
        batch.completed_at = None
        batch.requested_by_user_id = requested_by_user_id
        batch.transaction_count = 0
        batch.ledger_entry_count = 0
        batch.currency_count = 0
        batch.validation_issue_count = 0
        batch.is_balanced = True
        batch.failure_reason = None
        batch.updated_at = now
        db.add(batch)
        await db.commit()
        await db.refresh(batch)

        await self._execute_batch(db, batch)
        return await self._build_read_schema(db, batch)

    async def list_end_of_day_batches(
        self,
        db: AsyncSession,
        business_date: date | None = None,
        status_filter: EndOfDayBatchStatusEnum | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EndOfDayBatchReadSchema]:
        statement = select(EndOfDayBatch)
        if business_date is not None:
            statement = statement.where(EndOfDayBatch.business_date == business_date)
        if status_filter is not None:
            statement = statement.where(EndOfDayBatch.status == status_filter)
        statement = (
            statement.order_by(col(EndOfDayBatch.business_date).desc())
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(statement)
        batches = list(result.scalars().all())
        return [await self._build_read_schema(db, batch) for batch in batches]

    async def get_end_of_day_batch(
        self, db: AsyncSession, batch_id: uuid.UUID
    ) -> EndOfDayBatchReadSchema:
        batch = await db.get(EndOfDayBatch, batch_id)
        if batch is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="End-of-day batch not found",
            )
        return await self._build_read_schema(db, batch)

    async def _execute_batch(
        self, db: AsyncSession, batch: EndOfDayBatch
    ) -> None:
        start_at, end_at = self._business_day_window(batch.business_date)
        transactions = await self._get_transactions_for_business_day(
            db, start_at, end_at
        )
        transaction_ids = [transaction.id for transaction in transactions]
        entries_by_transaction_id = await self._get_entries_by_transaction_id(
            db, transaction_ids
        )
        daily_activity = await self._get_daily_ledger_activity(db, start_at, end_at)

        issues: list[EndOfDayBatchValidationIssue] = []
        valid_activity: list[tuple[LedgerEntry, Transaction]] = []

        for ledger_entry, transaction in daily_activity:
            has_valid_target = self._has_exactly_one_target(ledger_entry)
            currency_matches = ledger_entry.currency == transaction.currency

            if not has_valid_target:
                issues.append(
                    self._issue(
                        batch.id,
                        EndOfDayValidationIssueTypeEnum.INVALID_LEDGER_TARGET,
                        "Ledger entry must reference exactly one account target",
                        transaction_id=transaction.id,
                        ledger_entry_id=ledger_entry.id,
                    )
                )

            if not currency_matches:
                issues.append(
                    self._issue(
                        batch.id,
                        EndOfDayValidationIssueTypeEnum.CURRENCY_MISMATCH,
                        "Ledger entry currency does not match transaction currency",
                        transaction_id=transaction.id,
                        ledger_entry_id=ledger_entry.id,
                    )
                )

            if has_valid_target and currency_matches:
                valid_activity.append((ledger_entry, transaction))

        for transaction in transactions:
            entries = entries_by_transaction_id.get(transaction.id, [])

            if transaction.status in (
                TransactionStatusEnum.POSTED,
                TransactionStatusEnum.REVERSED,
            ):
                if not entries:
                    issues.append(
                        self._issue(
                            batch.id,
                            EndOfDayValidationIssueTypeEnum.MISSING_LEDGER_ENTRIES,
                            "Posted or reversed transaction has no ledger entries",
                            transaction_id=transaction.id,
                        )
                    )
                    continue

                debit_total, credit_total = self._sum_entry_amounts(entries)
                if debit_total != credit_total:
                    issues.append(
                        self._issue(
                            batch.id,
                            EndOfDayValidationIssueTypeEnum.UNBALANCED_TRANSACTION,
                            "Transaction ledger entries are not balanced",
                            transaction_id=transaction.id,
                        )
                    )

                for entry in entries:
                    if entry.currency != transaction.currency:
                        issues.append(
                            self._issue(
                                batch.id,
                                EndOfDayValidationIssueTypeEnum.CURRENCY_MISMATCH,
                                "Ledger entry currency does not match transaction currency",
                                transaction_id=transaction.id,
                                ledger_entry_id=entry.id,
                            )
                        )

            if transaction.status == TransactionStatusEnum.FAILED and entries:
                issues.append(
                    self._issue(
                        batch.id,
                        EndOfDayValidationIssueTypeEnum.FAILED_TRANSACTION_HAS_LEDGER_ENTRIES,
                        "Failed transaction has ledger entries",
                        transaction_id=transaction.id,
                    )
                )

        summaries = self._build_currency_summaries(batch.id, valid_activity)
        all_summaries_balanced = all(summary.is_balanced for summary in summaries)

        now = self._utc_now()
        batch.transaction_count = len(transactions)
        batch.ledger_entry_count = len(daily_activity)
        batch.currency_count = len(summaries)
        batch.validation_issue_count = len(issues)
        batch.is_balanced = len(issues) == 0 and all_summaries_balanced
        batch.status = (
            EndOfDayBatchStatusEnum.COMPLETED
            if batch.is_balanced
            else EndOfDayBatchStatusEnum.FAILED
        )
        batch.failure_reason = None if batch.is_balanced else "Validation failed"
        batch.completed_at = now
        batch.updated_at = now

        db.add(batch)
        for summary in summaries:
            db.add(summary)
        for issue in issues:
            db.add(issue)
        await db.commit()
        await db.refresh(batch)

    async def _get_batch_by_business_date_for_update(
        self, db: AsyncSession, business_date: date
    ) -> EndOfDayBatch | None:
        statement = (
            select(EndOfDayBatch)
            .where(EndOfDayBatch.business_date == business_date)
            .with_for_update()
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def _clear_batch_results(
        self, db: AsyncSession, batch_id: uuid.UUID
    ) -> None:
        await db.execute(
            delete(EndOfDayBatchCurrencySummary).where(
                col(EndOfDayBatchCurrencySummary.batch_id) == batch_id
            )
        )
        await db.execute(
            delete(EndOfDayBatchValidationIssue).where(
                col(EndOfDayBatchValidationIssue.batch_id) == batch_id
            )
        )

    async def _get_transactions_for_business_day(
        self, db: AsyncSession, start_at: datetime, end_at: datetime
    ) -> list[Transaction]:
        accounting_date = func.coalesce(Transaction.posted_at, Transaction.created_at)
        statement = (
            select(Transaction)
            .where(accounting_date >= start_at)
            .where(accounting_date < end_at)
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def _get_entries_by_transaction_id(
        self, db: AsyncSession, transaction_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[LedgerEntry]]:
        if not transaction_ids:
            return {}
        result = await db.execute(
            select(LedgerEntry).where(
                col(LedgerEntry.transaction_id).in_(transaction_ids)
            )
        )
        entries_by_transaction_id: dict[uuid.UUID, list[LedgerEntry]] = {}
        for entry in result.scalars().all():
            entries_by_transaction_id.setdefault(entry.transaction_id, []).append(entry)
        return entries_by_transaction_id

    async def _get_daily_ledger_activity(
        self, db: AsyncSession, start_at: datetime, end_at: datetime
    ) -> list[tuple[LedgerEntry, Transaction]]:
        accounting_date = func.coalesce(Transaction.posted_at, LedgerEntry.created_at)
        statement = (
            select(LedgerEntry, Transaction)
            .join(Transaction, col(LedgerEntry.transaction_id) == col(Transaction.id))
            .where(accounting_date >= start_at)
            .where(accounting_date < end_at)
        )
        result = await db.execute(statement)
        return [(row[0], row[1]) for row in result.all()]

    def _build_currency_summaries(
        self,
        batch_id: uuid.UUID,
        daily_activity: list[tuple[LedgerEntry, Transaction]],
    ) -> list[EndOfDayBatchCurrencySummary]:
        accumulators: dict[AccountCurrencyEnum, _CurrencyAccumulator] = {}
        for ledger_entry, transaction in daily_activity:
            accumulator = accumulators.setdefault(
                ledger_entry.currency,
                _CurrencyAccumulator(currency=ledger_entry.currency),
            )
            accumulator.transaction_ids.add(transaction.id)
            accumulator.ledger_entry_count += 1
            amount = self._normalize_amount(ledger_entry.amount)
            if ledger_entry.entry_type == LedgerEntryTypeEnum.DEBIT:
                accumulator.total_debit += amount
            else:
                accumulator.total_credit += amount

        summaries: list[EndOfDayBatchCurrencySummary] = []
        for currency in sorted(accumulators, key=lambda item: item.value):
            accumulator = accumulators[currency]
            total_debit = self._normalize_amount(accumulator.total_debit)
            total_credit = self._normalize_amount(accumulator.total_credit)
            summaries.append(
                EndOfDayBatchCurrencySummary(
                    batch_id=batch_id,
                    currency=currency,
                    transaction_count=len(accumulator.transaction_ids),
                    ledger_entry_count=accumulator.ledger_entry_count,
                    total_debit=total_debit,
                    total_credit=total_credit,
                    is_balanced=total_debit == total_credit,
                )
            )
        return summaries

    async def _build_read_schema(
        self, db: AsyncSession, batch: EndOfDayBatch
    ) -> EndOfDayBatchReadSchema:
        summaries_result = await db.execute(
            select(EndOfDayBatchCurrencySummary)
            .where(EndOfDayBatchCurrencySummary.batch_id == batch.id)
            .order_by(EndOfDayBatchCurrencySummary.currency)
        )
        issues_result = await db.execute(
            select(EndOfDayBatchValidationIssue)
            .where(EndOfDayBatchValidationIssue.batch_id == batch.id)
            .order_by(col(EndOfDayBatchValidationIssue.created_at))
        )
        summaries = [
            EndOfDayBatchCurrencySummaryReadSchema.model_validate(summary)
            for summary in summaries_result.scalars().all()
        ]
        validation_issues = [
            EndOfDayBatchValidationIssueReadSchema.model_validate(issue)
            for issue in issues_result.scalars().all()
        ]
        return EndOfDayBatchReadSchema(
            id=batch.id,
            business_date=batch.business_date,
            status=batch.status,
            started_at=batch.started_at,
            completed_at=batch.completed_at,
            requested_by_user_id=batch.requested_by_user_id,
            transaction_count=batch.transaction_count,
            ledger_entry_count=batch.ledger_entry_count,
            currency_count=batch.currency_count,
            validation_issue_count=batch.validation_issue_count,
            is_balanced=batch.is_balanced,
            failure_reason=batch.failure_reason,
            summaries=summaries,
            validation_issues=validation_issues,
        )

    def _issue(
        self,
        batch_id: uuid.UUID,
        issue_type: EndOfDayValidationIssueTypeEnum,
        message: str,
        transaction_id: uuid.UUID | None = None,
        ledger_entry_id: uuid.UUID | None = None,
    ) -> EndOfDayBatchValidationIssue:
        return EndOfDayBatchValidationIssue(
            batch_id=batch_id,
            issue_type=issue_type,
            message=message,
            transaction_id=transaction_id,
            ledger_entry_id=ledger_entry_id,
        )

    def _has_exactly_one_target(self, entry: LedgerEntry) -> bool:
        return (entry.customer_account_id is not None) != (
            entry.internal_account_id is not None
        )

    def _sum_entry_amounts(
        self, entries: list[LedgerEntry]
    ) -> tuple[Decimal, Decimal]:
        total_debit = Decimal("0.00")
        total_credit = Decimal("0.00")
        for entry in entries:
            amount = self._normalize_amount(entry.amount)
            if entry.entry_type == LedgerEntryTypeEnum.DEBIT:
                total_debit += amount
            else:
                total_credit += amount
        return self._normalize_amount(total_debit), self._normalize_amount(
            total_credit
        )

    def _business_day_window(self, business_date: date) -> tuple[datetime, datetime]:
        start_at = datetime.combine(business_date, time.min)
        end_at = datetime.combine(business_date + timedelta(days=1), time.min)
        return start_at, end_at

    def _normalize_amount(self, amount: Decimal) -> Decimal:
        return amount.quantize(CENT)

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)


end_of_day_batch_service = EndOfDayBatchService()
