import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from modules.accounts.enums import (
    AccountCurrencyEnum,
    AccountStatusEnum,
    AccountTypeEnum,
    InternalAccountTypeEnum,
)
from modules.accounts.models import BankAccount, InternalAccount
from modules.auth.services import auth_service
from modules.batches.enums import (
    EndOfDayBatchStatusEnum,
    EndOfDayValidationIssueSeverityEnum,
    EndOfDayValidationIssueTypeEnum,
)
from modules.batches.models import EndOfDayBatch
from modules.daily_balance_snapshots.models import DailyBalanceSnapshot
from modules.transactions.enums import (
    LedgerEntryTypeEnum,
    TransactionStatusEnum,
    TransactionTypeEnum,
)
from modules.transactions.models import FeeRule, LedgerEntry, Transaction
from modules.users.models import User
from modules.users.schemas import (
    AccountStatusSchema,
    RoleChoicesSchema,
    SecurityQuestionsSchema,
)

pytestmark = pytest.mark.asyncio


async def create_role_user(
    db: AsyncSession, username: str, role: RoleChoicesSchema
) -> User:
    username = username[:12]
    user = User(
        username=username,
        email=f"{username}@example.com",
        full_name=f"Full Name {username}",
        id_no=uuid.uuid4().int % 100000000 + 1,
        security_question=SecurityQuestionsSchema.FAVORITE_COLOR,
        security_answer_hash=auth_service.get_password_hash("blue"),
        hashed_password=auth_service.get_password_hash("password123"),
        is_active=True,
        is_superuser=(role == RoleChoicesSchema.SUPER_ADMIN),
        account_status=AccountStatusSchema.ACTIVE,
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def login_and_get_cookie(client: AsyncClient, email: str) -> dict[str, str]:
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert resp.status_code == 200
    token = resp.cookies.get("access_token")
    assert token is not None
    client.cookies.clear()
    return {"access_token": token}


async def create_active_account(
    db: AsyncSession,
    user_id: uuid.UUID,
    balance: Decimal = Decimal("1000.00"),
    currency: AccountCurrencyEnum = AccountCurrencyEnum.GBP,
    account_name: str = "End of Day Account",
) -> BankAccount:
    account = BankAccount(
        user_id=user_id,
        account_number=f"EOD{uuid.uuid4().hex[:8].upper()}",
        account_name=account_name,
        account_type=AccountTypeEnum.SAVINGS,
        currency=currency,
        account_status=AccountStatusEnum.ACTIVE,
        available_balance=balance,
        current_balance=balance,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


async def create_internal_account(
    db: AsyncSession,
    currency: AccountCurrencyEnum = AccountCurrencyEnum.GBP,
) -> InternalAccount:
    account = InternalAccount(
        account_code=f"EOD-INTERNAL-{uuid.uuid4().hex[:10].upper()}",
        account_name="End of Day Internal Account",
        account_type=InternalAccountTypeEnum.CASH_SETTLEMENT,
        currency=currency,
        balance=Decimal("0.00"),
        is_active=True,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


async def deactivate_fee_rules(
    db: AsyncSession,
    transaction_type: TransactionTypeEnum,
    currency: AccountCurrencyEnum,
) -> None:
    result = await db.execute(
        select(FeeRule).where(
            FeeRule.transaction_type == transaction_type,
            FeeRule.currency == currency,
        )
    )
    for rule in result.scalars().all():
        rule.is_active = False
        db.add(rule)
    await db.commit()


async def create_fee_rule(
    db: AsyncSession,
    currency: AccountCurrencyEnum,
    fixed_amount: Decimal,
) -> FeeRule:
    rule = FeeRule(
        transaction_type=TransactionTypeEnum.TRANSFER,
        currency=currency,
        fixed_amount=fixed_amount,
        is_active=True,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


async def post_deposit(
    client: AsyncClient,
    cookie: dict[str, str],
    account_id: uuid.UUID,
    amount: str,
) -> dict:
    client.cookies.clear()
    client.cookies.update(cookie)
    resp = await client.post(
        "/api/v1/admin/transactions/deposit",
        json={
            "destination_account_id": str(account_id),
            "amount": amount,
            "description": "End of day deposit",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def post_withdrawal(
    client: AsyncClient,
    cookie: dict[str, str],
    account_id: uuid.UUID,
    amount: str,
) -> dict:
    client.cookies.clear()
    client.cookies.update(cookie)
    resp = await client.post(
        "/api/v1/admin/transactions/withdrawal",
        json={
            "source_account_id": str(account_id),
            "amount": amount,
            "description": "End of day withdrawal",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def post_transfer(
    client: AsyncClient,
    cookie: dict[str, str],
    source_account_id: uuid.UUID,
    destination_account_id: uuid.UUID,
    amount: str,
) -> dict:
    client.cookies.clear()
    client.cookies.update(cookie)
    resp = await client.post(
        "/api/v1/customer/transactions/transfer",
        json={
            "source_account_id": str(source_account_id),
            "destination_account_id": str(destination_account_id),
            "amount": amount,
            "description": "End of day transfer",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def post_interest(
    client: AsyncClient,
    cookie: dict[str, str],
    account_id: uuid.UUID,
    amount: str,
) -> dict:
    client.cookies.clear()
    client.cookies.update(cookie)
    resp = await client.post(
        "/api/v1/admin/transactions/interest-posting",
        json={
            "destination_account_id": str(account_id),
            "amount": amount,
            "description": "End of day interest",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def reverse_transaction(
    client: AsyncClient,
    cookie: dict[str, str],
    transaction_id: str,
) -> dict:
    client.cookies.clear()
    client.cookies.update(cookie)
    resp = await client.post(
        f"/api/v1/admin/transactions/{transaction_id}/reverse",
        json={"reason": "End of day reversal"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def run_end_of_day(
    client: AsyncClient,
    cookie: dict[str, str],
    business_date: date,
    *,
    run_notes: str | None = None,
    check_daily_snapshots: bool = False,
) -> dict:
    client.cookies.clear()
    client.cookies.update(cookie)
    payload: dict[str, object] = {"business_date": business_date.isoformat()}
    if run_notes is not None:
        payload["run_notes"] = run_notes
    if check_daily_snapshots:
        payload["check_daily_snapshots"] = check_daily_snapshots
    resp = await client.post(
        "/api/v1/admin/batches/end-of-day",
        json=payload,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def move_transactions_to_business_date(
    db: AsyncSession,
    transaction_ids: list[str],
    business_date: date,
) -> None:
    for index, transaction_id in enumerate(transaction_ids):
        transaction = await db.get(Transaction, uuid.UUID(transaction_id))
        assert transaction is not None
        transaction.posted_at = datetime(
            business_date.year,
            business_date.month,
            business_date.day,
            12,
            0,
            index,
        )
        db.add(transaction)
    await db.commit()


def decimal_value(value: object) -> Decimal:
    return Decimal(str(value))


def summary_by_currency(batch: dict, currency: AccountCurrencyEnum) -> dict:
    return next(
        summary
        for summary in batch["summaries"]
        if summary["currency"] == currency.value
    )


def issue_messages(batch: dict, issue_type: EndOfDayValidationIssueTypeEnum) -> list[str]:
    return [
        issue["message"]
        for issue in batch["validation_issues"]
        if issue["issue_type"] == issue_type.value
    ]


async def create_daily_snapshot(
    db: AsyncSession,
    account: BankAccount,
    business_date: date,
) -> DailyBalanceSnapshot:
    snapshot = DailyBalanceSnapshot(
        account_id=account.id,
        business_date=business_date,
        currency=account.currency,
        opening_balance=account.current_balance,
        closing_balance=account.current_balance,
        available_balance=account.available_balance,
        current_balance=account.current_balance,
        transaction_count=1,
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)
    return snapshot


async def create_manual_transaction(
    db: AsyncSession,
    actor_user_id: uuid.UUID,
    business_date: date,
    *,
    amount: Decimal,
    status: TransactionStatusEnum = TransactionStatusEnum.POSTED,
    transaction_type: TransactionTypeEnum = TransactionTypeEnum.DEPOSIT,
    currency: AccountCurrencyEnum = AccountCurrencyEnum.GBP,
    posted_at: datetime | None = None,
) -> Transaction:
    transaction = Transaction(
        reference=f"EOD-{uuid.uuid4().hex[:14].upper()}",
        transaction_type=transaction_type,
        status=status,
        amount=amount,
        fee_amount=Decimal("0.00"),
        total_debit_amount=amount,
        currency=currency,
        description="Manual end-of-day validation fixture",
        created_by_user_id=actor_user_id,
        posted_at=posted_at
        if posted_at is not None
        else datetime(
            business_date.year,
            business_date.month,
            business_date.day,
            10,
            0,
        ),
        created_at=datetime(
            business_date.year,
            business_date.month,
            business_date.day,
            9,
            0,
        ),
    )
    db.add(transaction)
    await db.flush()
    return transaction


def add_ledger_entry(
    db: AsyncSession,
    transaction_id: uuid.UUID,
    *,
    entry_type: LedgerEntryTypeEnum,
    amount: Decimal,
    currency: AccountCurrencyEnum = AccountCurrencyEnum.GBP,
    customer_account_id: uuid.UUID | None = None,
    internal_account_id: uuid.UUID | None = None,
) -> LedgerEntry:
    entry = LedgerEntry(
        transaction_id=transaction_id,
        customer_account_id=customer_account_id,
        internal_account_id=internal_account_id,
        entry_type=entry_type,
        amount=amount,
        currency=currency,
        balance_after=amount,
    )
    db.add(entry)
    return entry


async def test_end_of_day_auth_rbac_missing_invalid_and_empty_close(
    client: AsyncClient,
):
    from infrastructure.database import engine

    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(
            db, f"eod_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        teller = await create_role_user(
            db, f"eod_t_{unique}", RoleChoicesSchema.TELLER
        )
        account_exec = await create_role_user(
            db, f"eod_ae_{unique}", RoleChoicesSchema.ACCOUNT_EXECUTIVE
        )
        branch_manager = await create_role_user(
            db, f"eod_bm_{unique}", RoleChoicesSchema.BRANCH_MANAGER
        )
        admin = await create_role_user(
            db, f"eod_ad_{unique}", RoleChoicesSchema.ADMIN
        )
        super_admin = await create_role_user(
            db, f"eod_sa_{unique}", RoleChoicesSchema.SUPER_ADMIN
        )

    cookies = {
        "customer": await login_and_get_cookie(client, customer.email),
        "teller": await login_and_get_cookie(client, teller.email),
        "account_exec": await login_and_get_cookie(client, account_exec.email),
        "branch_manager": await login_and_get_cookie(client, branch_manager.email),
        "admin": await login_and_get_cookie(client, admin.email),
        "super_admin": await login_and_get_cookie(client, super_admin.email),
    }

    client.cookies.clear()
    resp = await client.get("/api/v1/admin/batches/end-of-day")
    assert resp.status_code == 401

    resp = await client.post(
        "/api/v1/admin/batches/end-of-day",
        json={"business_date": "2038-01-01"},
    )
    assert resp.status_code == 401

    for role_name in ("customer", "teller", "account_exec"):
        client.cookies.clear()
        client.cookies.update(cookies[role_name])
        resp = await client.get("/api/v1/admin/batches/end-of-day")
        assert resp.status_code == 403

        resp = await client.post(
            "/api/v1/admin/batches/end-of-day",
            json={"business_date": "2038-01-01"},
        )
        assert resp.status_code == 403

    client.cookies.clear()
    client.cookies.update(cookies["branch_manager"])
    resp = await client.get("/api/v1/admin/batches/end-of-day")
    assert resp.status_code == 200

    resp = await client.post(
        "/api/v1/admin/batches/end-of-day",
        json={"business_date": "2038-01-01"},
    )
    assert resp.status_code == 403

    client.cookies.clear()
    client.cookies.update(cookies["admin"])
    resp = await client.post("/api/v1/admin/batches/end-of-day", json={})
    assert resp.status_code == 422

    resp = await client.post(
        "/api/v1/admin/batches/end-of-day",
        json={"business_date": "not-a-date"},
    )
    assert resp.status_code == 422

    admin_batch = await run_end_of_day(
        client,
        cookies["admin"],
        date(2038, 1, 1),
        run_notes="empty close check",
    )
    assert admin_batch["status"] == EndOfDayBatchStatusEnum.COMPLETED.value
    assert admin_batch["transaction_count"] == 0
    assert admin_batch["ledger_entry_count"] == 0
    assert admin_batch["currency_count"] == 0
    assert admin_batch["validation_issue_count"] == 0
    assert admin_batch["error_issue_count"] == 0
    assert admin_batch["warning_issue_count"] == 0
    assert admin_batch["snapshot_count"] == 0
    assert admin_batch["snapshot_missing_count"] == 0
    assert admin_batch["check_daily_snapshots"] is False
    assert admin_batch["run_notes"] == "empty close check"
    assert admin_batch["is_balanced"] is True
    assert admin_batch["summaries"] == []
    assert admin_batch["validation_issues"] == []

    super_admin_batch = await run_end_of_day(
        client, cookies["super_admin"], date(2038, 1, 2)
    )
    assert super_admin_batch["status"] == EndOfDayBatchStatusEnum.COMPLETED.value


async def test_end_of_day_activity_summaries_duplicates_list_and_detail(
    client: AsyncClient,
):
    from infrastructure.database import engine

    business_date = date(2099, 5, 1)
    currency = AccountCurrencyEnum.GBP
    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        await deactivate_fee_rules(db, TransactionTypeEnum.TRANSFER, currency)
        await create_fee_rule(db, currency, Decimal("2.00"))
        customer = await create_role_user(
            db, f"eodp_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        admin = await create_role_user(
            db, f"eodp_a_{unique}", RoleChoicesSchema.ADMIN
        )
        source = await create_active_account(
            db, customer.id, Decimal("1000.00"), currency, "EOD Source"
        )
        destination = await create_active_account(
            db, customer.id, Decimal("0.00"), currency, "EOD Destination"
        )
        reversed_account = await create_active_account(
            db, customer.id, Decimal("0.00"), currency, "EOD Reversed"
        )
        eur_account = await create_active_account(
            db, customer.id, Decimal("0.00"), AccountCurrencyEnum.EUR, "EOD EUR"
        )

    admin_cookie = await login_and_get_cookie(client, admin.email)
    customer_cookie = await login_and_get_cookie(client, customer.email)

    deposit = await post_deposit(client, admin_cookie, source.id, "500.00")
    withdrawal = await post_withdrawal(client, admin_cookie, source.id, "100.00")
    transfer = await post_transfer(
        client, customer_cookie, source.id, destination.id, "150.00"
    )
    interest = await post_interest(client, admin_cookie, destination.id, "25.50")
    reversed_deposit = await post_deposit(
        client, admin_cookie, reversed_account.id, "60.00"
    )
    reversal = await reverse_transaction(client, admin_cookie, reversed_deposit["id"])
    eur_deposit = await post_deposit(client, admin_cookie, eur_account.id, "77.00")

    async with AsyncSession(engine, expire_on_commit=False) as db:
        await move_transactions_to_business_date(
            db,
            [
                deposit["id"],
                withdrawal["id"],
                transfer["id"],
                interest["id"],
                reversed_deposit["id"],
                reversal["id"],
                eur_deposit["id"],
            ],
            business_date,
        )

    batch = await run_end_of_day(client, admin_cookie, business_date)
    assert batch["status"] == EndOfDayBatchStatusEnum.COMPLETED.value
    assert batch["transaction_count"] == 7
    assert batch["ledger_entry_count"] == 15
    assert batch["currency_count"] == 2
    assert batch["validation_issue_count"] == 0
    assert batch["error_issue_count"] == 0
    assert batch["warning_issue_count"] == 0
    assert batch["snapshot_count"] == 0
    assert batch["snapshot_missing_count"] == 0
    assert batch["check_daily_snapshots"] is False
    assert batch["run_notes"] is None
    assert batch["is_balanced"] is True
    assert batch["failure_reason"] is None

    gbp_summary = summary_by_currency(batch, currency)
    assert gbp_summary["transaction_count"] == 6
    assert gbp_summary["ledger_entry_count"] == 13
    assert decimal_value(gbp_summary["total_debit"]) == Decimal("897.50")
    assert decimal_value(gbp_summary["total_credit"]) == Decimal("897.50")
    assert gbp_summary["is_balanced"] is True

    eur_summary = summary_by_currency(batch, AccountCurrencyEnum.EUR)
    assert eur_summary["transaction_count"] == 1
    assert eur_summary["ledger_entry_count"] == 2
    assert decimal_value(eur_summary["total_debit"]) == Decimal("77.00")
    assert decimal_value(eur_summary["total_credit"]) == Decimal("77.00")
    assert eur_summary["is_balanced"] is True

    duplicate = await run_end_of_day(
        client,
        admin_cookie,
        business_date,
        run_notes="must not mutate completed close",
        check_daily_snapshots=True,
    )
    assert duplicate["id"] == batch["id"]
    assert duplicate["completed_at"] == batch["completed_at"]
    assert duplicate["validation_issue_count"] == 0
    assert duplicate["warning_issue_count"] == 0
    assert duplicate["check_daily_snapshots"] is False
    assert duplicate["run_notes"] is None

    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.get(
        "/api/v1/admin/batches/end-of-day",
        params={
            "business_date": business_date.isoformat(),
            "status": EndOfDayBatchStatusEnum.COMPLETED.value,
        },
    )
    assert resp.status_code == 200
    listed = resp.json()
    assert [item["id"] for item in listed] == [batch["id"]]

    resp = await client.get(f"/api/v1/admin/batches/end-of-day/{batch['id']}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["id"] == batch["id"]
    assert detail["business_date"] == business_date.isoformat()


async def test_end_of_day_failed_batch_can_rerun_after_data_is_fixed(
    client: AsyncClient,
):
    from infrastructure.database import engine

    business_date = date(2099, 5, 2)
    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(
            db, f"eodf_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        admin = await create_role_user(
            db, f"eodf_a_{unique}", RoleChoicesSchema.ADMIN
        )
        account = await create_active_account(
            db, customer.id, Decimal("0.00"), AccountCurrencyEnum.GBP
        )
        internal_account = await create_internal_account(db, AccountCurrencyEnum.GBP)
        transaction = await create_manual_transaction(
            db,
            admin.id,
            business_date,
            amount=Decimal("12.34"),
            currency=AccountCurrencyEnum.GBP,
        )
        await db.commit()

    admin_cookie = await login_and_get_cookie(client, admin.email)
    failed_batch = await run_end_of_day(
        client,
        admin_cookie,
        business_date,
        run_notes="first failed run",
        check_daily_snapshots=True,
    )
    assert failed_batch["status"] == EndOfDayBatchStatusEnum.FAILED.value
    assert failed_batch["failure_reason"] == "Validation failed"
    assert failed_batch["is_balanced"] is False
    assert failed_batch["validation_issue_count"] == 1
    assert failed_batch["error_issue_count"] == 1
    assert failed_batch["warning_issue_count"] == 0
    assert failed_batch["snapshot_count"] == 0
    assert failed_batch["snapshot_missing_count"] == 0
    assert failed_batch["check_daily_snapshots"] is True
    assert failed_batch["run_notes"] == "first failed run"
    assert failed_batch["validation_issues"][0]["issue_type"] == (
        EndOfDayValidationIssueTypeEnum.MISSING_LEDGER_ENTRIES.value
    )
    assert failed_batch["validation_issues"][0]["severity"] == (
        EndOfDayValidationIssueSeverityEnum.ERROR.value
    )

    async with AsyncSession(engine, expire_on_commit=False) as db:
        add_ledger_entry(
            db,
            transaction.id,
            entry_type=LedgerEntryTypeEnum.DEBIT,
            amount=Decimal("12.34"),
            internal_account_id=internal_account.id,
        )
        add_ledger_entry(
            db,
            transaction.id,
            entry_type=LedgerEntryTypeEnum.CREDIT,
            amount=Decimal("12.34"),
            customer_account_id=account.id,
        )
        await db.commit()

    completed_batch = await run_end_of_day(
        client,
        admin_cookie,
        business_date,
        run_notes="fixed rerun",
    )
    assert completed_batch["id"] == failed_batch["id"]
    assert completed_batch["status"] == EndOfDayBatchStatusEnum.COMPLETED.value
    assert completed_batch["failure_reason"] is None
    assert completed_batch["validation_issue_count"] == 0
    assert completed_batch["error_issue_count"] == 0
    assert completed_batch["warning_issue_count"] == 0
    assert completed_batch["snapshot_count"] == 0
    assert completed_batch["snapshot_missing_count"] == 0
    assert completed_batch["check_daily_snapshots"] is False
    assert completed_batch["run_notes"] == "fixed rerun"
    assert completed_batch["validation_issues"] == []
    assert completed_batch["currency_count"] == 1

    summary = summary_by_currency(completed_batch, AccountCurrencyEnum.GBP)
    assert summary["transaction_count"] == 1
    assert summary["ledger_entry_count"] == 2
    assert decimal_value(summary["total_debit"]) == Decimal("12.34")
    assert decimal_value(summary["total_credit"]) == Decimal("12.34")


async def test_end_of_day_running_batch_conflict(client: AsyncClient):
    from infrastructure.database import engine

    business_date = date(2099, 5, 3)
    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        admin = await create_role_user(
            db, f"eodr_a_{unique}", RoleChoicesSchema.ADMIN
        )
        db.add(
            EndOfDayBatch(
                business_date=business_date,
                status=EndOfDayBatchStatusEnum.RUNNING,
                requested_by_user_id=admin.id,
            )
        )
        await db.commit()

    admin_cookie = await login_and_get_cookie(client, admin.email)
    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post(
        "/api/v1/admin/batches/end-of-day",
        json={"business_date": business_date.isoformat()},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "End-of-day batch is already running"


async def test_end_of_day_validation_issues_create_failed_batch(
    client: AsyncClient,
):
    from infrastructure.database import engine

    business_date = date(2099, 5, 4)
    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(
            db, f"eodv_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        admin = await create_role_user(
            db, f"eodv_a_{unique}", RoleChoicesSchema.ADMIN
        )
        account = await create_active_account(
            db, customer.id, Decimal("0.00"), AccountCurrencyEnum.GBP
        )
        internal_account = await create_internal_account(db, AccountCurrencyEnum.GBP)

        missing_entries = await create_manual_transaction(
            db,
            admin.id,
            business_date,
            amount=Decimal("1.00"),
            currency=AccountCurrencyEnum.GBP,
        )

        invalid_target = await create_manual_transaction(
            db,
            admin.id,
            business_date,
            amount=Decimal("2.00"),
            currency=AccountCurrencyEnum.GBP,
        )
        add_ledger_entry(
            db,
            invalid_target.id,
            entry_type=LedgerEntryTypeEnum.DEBIT,
            amount=Decimal("2.00"),
        )
        add_ledger_entry(
            db,
            invalid_target.id,
            entry_type=LedgerEntryTypeEnum.CREDIT,
            amount=Decimal("2.00"),
            customer_account_id=account.id,
        )

        unbalanced = await create_manual_transaction(
            db,
            admin.id,
            business_date,
            amount=Decimal("3.00"),
            currency=AccountCurrencyEnum.GBP,
        )
        add_ledger_entry(
            db,
            unbalanced.id,
            entry_type=LedgerEntryTypeEnum.DEBIT,
            amount=Decimal("3.00"),
            internal_account_id=internal_account.id,
        )
        add_ledger_entry(
            db,
            unbalanced.id,
            entry_type=LedgerEntryTypeEnum.CREDIT,
            amount=Decimal("2.00"),
            customer_account_id=account.id,
        )

        mismatch = await create_manual_transaction(
            db,
            admin.id,
            business_date,
            amount=Decimal("4.00"),
            currency=AccountCurrencyEnum.GBP,
        )
        add_ledger_entry(
            db,
            mismatch.id,
            entry_type=LedgerEntryTypeEnum.DEBIT,
            amount=Decimal("4.00"),
            currency=AccountCurrencyEnum.GBP,
            internal_account_id=internal_account.id,
        )
        add_ledger_entry(
            db,
            mismatch.id,
            entry_type=LedgerEntryTypeEnum.CREDIT,
            amount=Decimal("4.00"),
            currency=AccountCurrencyEnum.EUR,
            customer_account_id=account.id,
        )

        failed_with_entries = await create_manual_transaction(
            db,
            admin.id,
            business_date,
            amount=Decimal("5.00"),
            status=TransactionStatusEnum.FAILED,
            currency=AccountCurrencyEnum.GBP,
            posted_at=None,
        )
        failed_with_entries.posted_at = None
        add_ledger_entry(
            db,
            failed_with_entries.id,
            entry_type=LedgerEntryTypeEnum.DEBIT,
            amount=Decimal("5.00"),
            internal_account_id=internal_account.id,
        )
        add_ledger_entry(
            db,
            failed_with_entries.id,
            entry_type=LedgerEntryTypeEnum.CREDIT,
            amount=Decimal("5.00"),
            customer_account_id=account.id,
        )

        await db.commit()

    admin_cookie = await login_and_get_cookie(client, admin.email)
    batch = await run_end_of_day(client, admin_cookie, business_date)
    assert batch["status"] == EndOfDayBatchStatusEnum.FAILED.value
    assert batch["failure_reason"] == "Validation failed"
    assert batch["is_balanced"] is False
    assert batch["validation_issue_count"] >= 5
    assert batch["error_issue_count"] == batch["validation_issue_count"]
    assert batch["warning_issue_count"] == 0
    assert all(
        issue["severity"] == EndOfDayValidationIssueSeverityEnum.ERROR.value
        for issue in batch["validation_issues"]
    )

    issue_types = {issue["issue_type"] for issue in batch["validation_issues"]}
    assert EndOfDayValidationIssueTypeEnum.INVALID_LEDGER_TARGET.value in issue_types
    assert EndOfDayValidationIssueTypeEnum.MISSING_LEDGER_ENTRIES.value in issue_types
    assert EndOfDayValidationIssueTypeEnum.UNBALANCED_TRANSACTION.value in issue_types
    assert EndOfDayValidationIssueTypeEnum.CURRENCY_MISMATCH.value in issue_types
    assert (
        EndOfDayValidationIssueTypeEnum.FAILED_TRANSACTION_HAS_LEDGER_ENTRIES.value
        in issue_types
    )

    invalid_target_messages = issue_messages(
        batch, EndOfDayValidationIssueTypeEnum.INVALID_LEDGER_TARGET
    )
    assert any(invalid_target.reference in message for message in invalid_target_messages)
    assert any("expected exactly one" in message for message in invalid_target_messages)
    assert any("no account target" in message for message in invalid_target_messages)

    missing_messages = issue_messages(
        batch, EndOfDayValidationIssueTypeEnum.MISSING_LEDGER_ENTRIES
    )
    assert any(missing_entries.reference in message for message in missing_messages)
    assert any("status posted" in message for message in missing_messages)

    unbalanced_messages = issue_messages(
        batch, EndOfDayValidationIssueTypeEnum.UNBALANCED_TRANSACTION
    )
    assert any(unbalanced.reference in message for message in unbalanced_messages)
    assert any("debit_total=3.00" in message for message in unbalanced_messages)
    assert any("credit_total=2.00" in message for message in unbalanced_messages)

    mismatch_messages = issue_messages(
        batch, EndOfDayValidationIssueTypeEnum.CURRENCY_MISMATCH
    )
    assert any(mismatch.reference in message for message in mismatch_messages)
    assert any("expected GBP, actual EUR" in message for message in mismatch_messages)

    failed_messages = issue_messages(
        batch,
        EndOfDayValidationIssueTypeEnum.FAILED_TRANSACTION_HAS_LEDGER_ENTRIES,
    )
    assert any(failed_with_entries.reference in message for message in failed_messages)
    assert any("expected none" in message for message in failed_messages)


async def test_end_of_day_missing_snapshot_warnings_are_non_fatal_and_distinct(
    client: AsyncClient,
):
    from infrastructure.database import engine

    business_date = date(2099, 5, 5)
    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(
            db, f"eods_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        admin = await create_role_user(
            db, f"eods_a_{unique}", RoleChoicesSchema.ADMIN
        )
        covered_account = await create_active_account(
            db, customer.id, Decimal("0.00"), AccountCurrencyEnum.GBP, "EOD Covered"
        )
        missing_account = await create_active_account(
            db, customer.id, Decimal("0.00"), AccountCurrencyEnum.GBP, "EOD Missing"
        )

    admin_cookie = await login_and_get_cookie(client, admin.email)
    covered_deposit = await post_deposit(client, admin_cookie, covered_account.id, "10.00")
    missing_deposit_one = await post_deposit(
        client, admin_cookie, missing_account.id, "20.00"
    )
    missing_deposit_two = await post_deposit(
        client, admin_cookie, missing_account.id, "30.00"
    )

    async with AsyncSession(engine, expire_on_commit=False) as db:
        await move_transactions_to_business_date(
            db,
            [
                covered_deposit["id"],
                missing_deposit_one["id"],
                missing_deposit_two["id"],
            ],
            business_date,
        )
        await create_daily_snapshot(db, covered_account, business_date)

    batch = await run_end_of_day(
        client,
        admin_cookie,
        business_date,
        run_notes="snapshot coverage check",
        check_daily_snapshots=True,
    )
    assert batch["status"] == EndOfDayBatchStatusEnum.COMPLETED.value
    assert batch["failure_reason"] is None
    assert batch["is_balanced"] is True
    assert batch["validation_issue_count"] == 1
    assert batch["error_issue_count"] == 0
    assert batch["warning_issue_count"] == 1
    assert batch["snapshot_count"] == 1
    assert batch["snapshot_missing_count"] == 1
    assert batch["check_daily_snapshots"] is True
    assert batch["run_notes"] == "snapshot coverage check"

    warning = batch["validation_issues"][0]
    assert warning["issue_type"] == (
        EndOfDayValidationIssueTypeEnum.MISSING_DAILY_BALANCE_SNAPSHOT.value
    )
    assert warning["severity"] == EndOfDayValidationIssueSeverityEnum.WARNING.value
    assert warning["currency"] == AccountCurrencyEnum.GBP.value
    assert warning["customer_account_id"] == str(missing_account.id)
    assert warning["transaction_id"] is None
    assert warning["ledger_entry_id"] is None

    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.get(
        f"/api/v1/admin/batches/end-of-day/{batch['id']}",
        params={
            "issue_type": (
                EndOfDayValidationIssueTypeEnum.MISSING_DAILY_BALANCE_SNAPSHOT.value
            ),
            "issue_severity": EndOfDayValidationIssueSeverityEnum.WARNING.value,
        },
    )
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["validation_issue_count"] == 1
    assert len(detail["validation_issues"]) == 1
    assert detail["validation_issues"][0]["id"] == warning["id"]


async def test_end_of_day_skips_snapshot_warnings_when_check_is_disabled(
    client: AsyncClient,
):
    from infrastructure.database import engine

    business_date = date(2099, 5, 6)
    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(
            db, f"eodn_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        admin = await create_role_user(
            db, f"eodn_a_{unique}", RoleChoicesSchema.ADMIN
        )
        account = await create_active_account(
            db, customer.id, Decimal("0.00"), AccountCurrencyEnum.GBP
        )

    admin_cookie = await login_and_get_cookie(client, admin.email)
    deposit = await post_deposit(client, admin_cookie, account.id, "12.00")

    async with AsyncSession(engine, expire_on_commit=False) as db:
        await move_transactions_to_business_date(
            db, [deposit["id"]], business_date
        )

    batch = await run_end_of_day(client, admin_cookie, business_date)
    assert batch["status"] == EndOfDayBatchStatusEnum.COMPLETED.value
    assert batch["validation_issue_count"] == 0
    assert batch["error_issue_count"] == 0
    assert batch["warning_issue_count"] == 0
    assert batch["snapshot_count"] == 0
    assert batch["snapshot_missing_count"] == 0
    assert batch["check_daily_snapshots"] is False


async def test_end_of_day_list_filters_and_detail_issue_filters(
    client: AsyncClient,
):
    from infrastructure.database import engine

    completed_date = date(2099, 5, 7)
    failed_date = date(2099, 5, 8)
    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(
            db, f"eodl_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        admin = await create_role_user(
            db, f"eodl_a_{unique}", RoleChoicesSchema.ADMIN
        )
        eur_account = await create_active_account(
            db, customer.id, Decimal("0.00"), AccountCurrencyEnum.EUR, "EOD EUR List"
        )
        await create_manual_transaction(
            db,
            admin.id,
            failed_date,
            amount=Decimal("45.00"),
            currency=AccountCurrencyEnum.GBP,
        )
        await db.commit()

    admin_cookie = await login_and_get_cookie(client, admin.email)
    eur_deposit = await post_deposit(client, admin_cookie, eur_account.id, "15.00")

    async with AsyncSession(engine, expire_on_commit=False) as db:
        await move_transactions_to_business_date(
            db, [eur_deposit["id"]], completed_date
        )

    completed_batch = await run_end_of_day(client, admin_cookie, completed_date)
    failed_batch = await run_end_of_day(client, admin_cookie, failed_date)
    assert completed_batch["status"] == EndOfDayBatchStatusEnum.COMPLETED.value
    assert failed_batch["status"] == EndOfDayBatchStatusEnum.FAILED.value

    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.get(
        "/api/v1/admin/batches/end-of-day",
        params={
            "business_date": completed_date.isoformat(),
            "from_date": completed_date.isoformat(),
        },
    )
    assert resp.status_code == 400

    resp = await client.get(
        "/api/v1/admin/batches/end-of-day",
        params={
            "from_date": failed_date.isoformat(),
            "to_date": completed_date.isoformat(),
        },
    )
    assert resp.status_code == 400

    resp = await client.get(
        "/api/v1/admin/batches/end-of-day",
        params={
            "from_date": completed_date.isoformat(),
            "to_date": failed_date.isoformat(),
            "currency": AccountCurrencyEnum.EUR.value,
        },
    )
    assert resp.status_code == 200
    assert [item["id"] for item in resp.json()] == [completed_batch["id"]]

    resp = await client.get(
        "/api/v1/admin/batches/end-of-day",
        params={
            "from_date": completed_date.isoformat(),
            "to_date": failed_date.isoformat(),
            "currency": AccountCurrencyEnum.GBP.value,
        },
    )
    assert resp.status_code == 200
    assert resp.json() == []

    resp = await client.get(
        "/api/v1/admin/batches/end-of-day",
        params={
            "from_date": completed_date.isoformat(),
            "to_date": failed_date.isoformat(),
            "has_validation_issues": "true",
        },
    )
    assert resp.status_code == 200
    assert [item["id"] for item in resp.json()] == [failed_batch["id"]]

    resp = await client.get(
        "/api/v1/admin/batches/end-of-day",
        params={
            "from_date": completed_date.isoformat(),
            "to_date": failed_date.isoformat(),
            "has_validation_issues": "false",
        },
    )
    assert resp.status_code == 200
    assert [item["id"] for item in resp.json()] == [completed_batch["id"]]

    resp = await client.get(
        "/api/v1/admin/batches/end-of-day",
        params={
            "from_date": completed_date.isoformat(),
            "to_date": failed_date.isoformat(),
            "is_balanced": "false",
        },
    )
    assert resp.status_code == 200
    assert [item["id"] for item in resp.json()] == [failed_batch["id"]]

    resp = await client.get(
        "/api/v1/admin/batches/end-of-day",
        params={
            "business_date": completed_date.isoformat(),
            "requested_by_user_id": str(admin.id),
        },
    )
    assert resp.status_code == 200
    assert [item["id"] for item in resp.json()] == [completed_batch["id"]]

    resp = await client.get(
        "/api/v1/admin/batches/end-of-day",
        params={
            "business_date": completed_date.isoformat(),
            "requested_by_user_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 200
    assert resp.json() == []

    resp = await client.get(
        f"/api/v1/admin/batches/end-of-day/{failed_batch['id']}",
        params={
            "issue_type": EndOfDayValidationIssueTypeEnum.MISSING_LEDGER_ENTRIES.value
        },
    )
    assert resp.status_code == 200
    issue_type_detail = resp.json()
    assert len(issue_type_detail["validation_issues"]) == 1
    assert issue_type_detail["validation_issues"][0]["issue_type"] == (
        EndOfDayValidationIssueTypeEnum.MISSING_LEDGER_ENTRIES.value
    )

    resp = await client.get(
        f"/api/v1/admin/batches/end-of-day/{failed_batch['id']}",
        params={"issue_severity": EndOfDayValidationIssueSeverityEnum.ERROR.value},
    )
    assert resp.status_code == 200
    severity_detail = resp.json()
    assert len(severity_detail["validation_issues"]) == 1
    assert severity_detail["validation_issues"][0]["severity"] == (
        EndOfDayValidationIssueSeverityEnum.ERROR.value
    )

    resp = await client.get(
        f"/api/v1/admin/batches/end-of-day/{failed_batch['id']}",
        params={"issue_severity": EndOfDayValidationIssueSeverityEnum.WARNING.value},
    )
    assert resp.status_code == 200
    assert resp.json()["validation_issues"] == []
