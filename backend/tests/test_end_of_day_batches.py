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
    EndOfDayValidationIssueTypeEnum,
)
from modules.batches.models import EndOfDayBatch
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
) -> dict:
    client.cookies.clear()
    client.cookies.update(cookie)
    resp = await client.post(
        "/api/v1/admin/batches/end-of-day",
        json={"business_date": business_date.isoformat()},
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
        client, cookies["admin"], date(2038, 1, 1)
    )
    assert admin_batch["status"] == EndOfDayBatchStatusEnum.COMPLETED.value
    assert admin_batch["transaction_count"] == 0
    assert admin_batch["ledger_entry_count"] == 0
    assert admin_batch["currency_count"] == 0
    assert admin_batch["validation_issue_count"] == 0
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

    duplicate = await run_end_of_day(client, admin_cookie, business_date)
    assert duplicate["id"] == batch["id"]
    assert duplicate["completed_at"] == batch["completed_at"]
    assert duplicate["validation_issue_count"] == 0

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
    failed_batch = await run_end_of_day(client, admin_cookie, business_date)
    assert failed_batch["status"] == EndOfDayBatchStatusEnum.FAILED.value
    assert failed_batch["failure_reason"] == "Validation failed"
    assert failed_batch["is_balanced"] is False
    assert failed_batch["validation_issue_count"] == 1
    assert failed_batch["validation_issues"][0]["issue_type"] == (
        EndOfDayValidationIssueTypeEnum.MISSING_LEDGER_ENTRIES.value
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

    completed_batch = await run_end_of_day(client, admin_cookie, business_date)
    assert completed_batch["id"] == failed_batch["id"]
    assert completed_batch["status"] == EndOfDayBatchStatusEnum.COMPLETED.value
    assert completed_batch["failure_reason"] is None
    assert completed_batch["validation_issue_count"] == 0
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

        await create_manual_transaction(
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

    issue_types = {issue["issue_type"] for issue in batch["validation_issues"]}
    assert EndOfDayValidationIssueTypeEnum.INVALID_LEDGER_TARGET.value in issue_types
    assert EndOfDayValidationIssueTypeEnum.MISSING_LEDGER_ENTRIES.value in issue_types
    assert EndOfDayValidationIssueTypeEnum.UNBALANCED_TRANSACTION.value in issue_types
    assert EndOfDayValidationIssueTypeEnum.CURRENCY_MISMATCH.value in issue_types
    assert (
        EndOfDayValidationIssueTypeEnum.FAILED_TRANSACTION_HAS_LEDGER_ENTRIES.value
        in issue_types
    )
