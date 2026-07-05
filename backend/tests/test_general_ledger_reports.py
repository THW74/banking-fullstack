import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from modules.accounts.enums import AccountCurrencyEnum, AccountStatusEnum, AccountTypeEnum
from modules.accounts.models import BankAccount
from modules.auth.services import auth_service
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
    balance: Decimal = Decimal("0.00"),
    currency: AccountCurrencyEnum = AccountCurrencyEnum.DKK,
    account_name: str = "General Ledger Account",
) -> BankAccount:
    account = BankAccount(
        user_id=user_id,
        account_number=f"GL{uuid.uuid4().hex[:8].upper()}",
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
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for rule in result.scalars().all():
        rule.is_active = False
        rule.updated_at = now
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
    description: str = "General ledger deposit",
) -> dict:
    client.cookies.clear()
    client.cookies.update(cookie)
    resp = await client.post(
        "/api/v1/admin/transactions/deposit",
        json={
            "destination_account_id": str(account_id),
            "amount": amount,
            "description": description,
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
            "description": "General ledger withdrawal",
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
            "description": "General ledger transfer",
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
            "description": "General ledger interest",
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
        json={"reason": "General ledger reversal"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def get_general_ledger(
    client: AsyncClient,
    cookie: dict[str, str],
    params: dict[str, str],
) -> dict:
    client.cookies.clear()
    client.cookies.update(cookie)
    resp = await client.get("/api/v1/admin/reports/general-ledger", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def decimal_value(value: object) -> Decimal:
    return Decimal(str(value))


def transaction_entries(report: dict, transaction_id: str) -> list[dict]:
    return [
        entry
        for entry in report["entries"]
        if entry["transaction_id"] == transaction_id
    ]


def entry_ids(report: dict) -> list[str]:
    return [entry["ledger_entry_id"] for entry in report["entries"]]


async def test_general_ledger_auth_rbac_validation_and_empty_report(
    client: AsyncClient,
):
    from infrastructure.database import engine

    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(
            db, f"gl_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        teller = await create_role_user(
            db, f"gl_t_{unique}", RoleChoicesSchema.TELLER
        )
        account_exec = await create_role_user(
            db, f"gl_ae_{unique}", RoleChoicesSchema.ACCOUNT_EXECUTIVE
        )
        branch_manager = await create_role_user(
            db, f"gl_bm_{unique}", RoleChoicesSchema.BRANCH_MANAGER
        )
        admin = await create_role_user(
            db, f"gl_ad_{unique}", RoleChoicesSchema.ADMIN
        )
        super_admin = await create_role_user(
            db, f"gl_sa_{unique}", RoleChoicesSchema.SUPER_ADMIN
        )

    cookies = {
        "customer": await login_and_get_cookie(client, customer.email),
        "teller": await login_and_get_cookie(client, teller.email),
        "account_exec": await login_and_get_cookie(client, account_exec.email),
        "branch_manager": await login_and_get_cookie(client, branch_manager.email),
        "admin": await login_and_get_cookie(client, admin.email),
        "super_admin": await login_and_get_cookie(client, super_admin.email),
    }
    params = {
        "currency": AccountCurrencyEnum.DKK.value,
        "from_date": "2000-01-01",
        "to_date": "2000-01-01",
    }

    client.cookies.clear()
    resp = await client.get("/api/v1/admin/reports/general-ledger", params=params)
    assert resp.status_code == 401

    for role_name in ("customer", "teller", "account_exec"):
        client.cookies.clear()
        client.cookies.update(cookies[role_name])
        resp = await client.get("/api/v1/admin/reports/general-ledger", params=params)
        assert resp.status_code == 403

    client.cookies.clear()
    client.cookies.update(cookies["admin"])
    resp = await client.get("/api/v1/admin/reports/general-ledger")
    assert resp.status_code == 422

    resp = await client.get(
        "/api/v1/admin/reports/general-ledger",
        params={
            "currency": AccountCurrencyEnum.DKK.value,
            "from_date": "2026-07-06",
            "to_date": "2026-07-05",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "from_date must be before or equal to to_date"

    resp = await client.get(
        "/api/v1/admin/reports/general-ledger",
        params={**params, "account_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == (
        "account_target_type is required when account_id is provided"
    )

    for role_name in ("branch_manager", "admin", "super_admin"):
        report = await get_general_ledger(client, cookies[role_name], params)
        assert report["currency"] == AccountCurrencyEnum.DKK.value
        assert decimal_value(report["total_debit"]) == Decimal("0.00")
        assert decimal_value(report["total_credit"]) == Decimal("0.00")
        assert report["entry_count"] == 0
        assert report["has_more"] is False
        assert report["entries"] == []


async def test_general_ledger_activity_filters_reversals_and_pagination(
    client: AsyncClient,
):
    from infrastructure.database import engine

    currency = AccountCurrencyEnum.GBP
    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        await deactivate_fee_rules(db, TransactionTypeEnum.TRANSFER, currency)
        await create_fee_rule(db, currency, fixed_amount=Decimal("2.00"))
        customer = await create_role_user(
            db, f"gla_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        admin = await create_role_user(
            db, f"gla_a_{unique}", RoleChoicesSchema.ADMIN
        )
        source = await create_active_account(
            db, customer.id, Decimal("0.00"), currency, "GL Source"
        )
        destination = await create_active_account(
            db, customer.id, Decimal("0.00"), currency, "GL Destination"
        )
        reversed_account = await create_active_account(
            db, customer.id, Decimal("0.00"), currency, "GL Reversed"
        )
        eur_account = await create_active_account(
            db, customer.id, Decimal("0.00"), AccountCurrencyEnum.EUR, "GL EUR"
        )

    admin_cookie = await login_and_get_cookie(client, admin.email)
    customer_cookie = await login_and_get_cookie(client, customer.email)
    report_date = datetime.now(timezone.utc).date()
    base_params = {
        "currency": currency.value,
        "from_date": report_date.isoformat(),
        "to_date": (report_date + timedelta(days=1)).isoformat(),
    }

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
    await post_deposit(client, admin_cookie, eur_account.id, "77.00")

    source_report = await get_general_ledger(
        client,
        admin_cookie,
        {
            **base_params,
            "account_target_type": "customer_account",
            "account_id": str(source.id),
        },
    )
    assert source_report["entry_count"] == 3
    assert decimal_value(source_report["total_debit"]) == Decimal("252.00")
    assert decimal_value(source_report["total_credit"]) == Decimal("500.00")
    assert source_report["has_more"] is False

    deposit_source_entries = transaction_entries(source_report, deposit["id"])
    assert len(deposit_source_entries) == 1
    assert deposit_source_entries[0]["account_code"] == source.account_number
    assert deposit_source_entries[0]["transaction_type"] == "deposit"
    assert deposit_source_entries[0]["entry_type"] == "credit"
    assert decimal_value(deposit_source_entries[0]["credit_amount"]) == Decimal("500.00")
    assert decimal_value(deposit_source_entries[0]["signed_amount"]) == Decimal("-500.00")
    assert deposit_source_entries[0]["accounting_date"] is not None
    assert deposit_source_entries[0]["posted_at"] is not None

    withdrawal_source_entries = transaction_entries(source_report, withdrawal["id"])
    assert len(withdrawal_source_entries) == 1
    assert withdrawal_source_entries[0]["transaction_type"] == "withdrawal"
    assert decimal_value(withdrawal_source_entries[0]["debit_amount"]) == Decimal("100.00")
    assert decimal_value(withdrawal_source_entries[0]["signed_amount"]) == Decimal("100.00")

    transfer_source_entries = transaction_entries(source_report, transfer["id"])
    assert len(transfer_source_entries) == 1
    assert transfer_source_entries[0]["transaction_type"] == "transfer"
    assert decimal_value(transfer_source_entries[0]["debit_amount"]) == Decimal("152.00")

    destination_report = await get_general_ledger(
        client,
        admin_cookie,
        {**base_params, "account_code": destination.account_number},
    )
    assert destination_report["entry_count"] == 2
    assert decimal_value(destination_report["total_debit"]) == Decimal("0.00")
    assert decimal_value(destination_report["total_credit"]) == Decimal("175.50")
    assert len(transaction_entries(destination_report, transfer["id"])) == 1
    assert len(transaction_entries(destination_report, interest["id"])) == 1

    transfer_report = await get_general_ledger(
        client,
        admin_cookie,
        {
            **base_params,
            "account_target_type": "customer_account",
            "account_id": str(source.id),
            "transaction_type": "transfer",
        },
    )
    assert transfer_report["entry_count"] == 1
    assert transfer_report["entries"][0]["transaction_id"] == transfer["id"]

    fee_report = await get_general_ledger(
        client,
        admin_cookie,
        {
            **base_params,
            "account_target_type": "internal_account",
            "account_code": f"FEE-INCOME-{currency.value}",
        },
    )
    fee_entries = transaction_entries(fee_report, transfer["id"])
    assert len(fee_entries) == 1
    assert fee_entries[0]["account_target_type"] == "internal_account"
    assert decimal_value(fee_entries[0]["credit_amount"]) == Decimal("2.00")
    assert decimal_value(fee_entries[0]["signed_amount"]) == Decimal("-2.00")

    interest_report = await get_general_ledger(
        client,
        admin_cookie,
        {
            **base_params,
            "account_target_type": "internal_account",
            "account_code": f"INTEREST-EXPENSE-{currency.value}",
        },
    )
    interest_entries = transaction_entries(interest_report, interest["id"])
    assert len(interest_entries) == 1
    assert decimal_value(interest_entries[0]["debit_amount"]) == Decimal("25.50")
    assert decimal_value(interest_entries[0]["signed_amount"]) == Decimal("25.50")

    reversed_report = await get_general_ledger(
        client,
        admin_cookie,
        {
            **base_params,
            "account_target_type": "customer_account",
            "account_id": str(reversed_account.id),
        },
    )
    assert reversed_report["entry_count"] == 2
    assert decimal_value(reversed_report["total_debit"]) == Decimal("60.00")
    assert decimal_value(reversed_report["total_credit"]) == Decimal("60.00")
    assert len(transaction_entries(reversed_report, reversed_deposit["id"])) == 1
    assert len(transaction_entries(reversed_report, reversal["id"])) == 1
    original_entry = transaction_entries(reversed_report, reversed_deposit["id"])[0]
    reversal_entry = transaction_entries(reversed_report, reversal["id"])[0]
    assert original_entry["transaction_status"] == "reversed"
    assert original_entry["entry_type"] == "credit"
    assert reversal_entry["transaction_type"] == "reversal"
    assert reversal_entry["entry_type"] == "debit"

    eur_filtered_report = await get_general_ledger(
        client,
        admin_cookie,
        {
            **base_params,
            "account_target_type": "customer_account",
            "account_id": str(eur_account.id),
        },
    )
    assert eur_filtered_report["entry_count"] == 0
    assert eur_filtered_report["entries"] == []

    full_source_report = await get_general_ledger(
        client,
        admin_cookie,
        {
            **base_params,
            "account_target_type": "customer_account",
            "account_id": str(source.id),
            "limit": "10",
        },
    )
    first_page = await get_general_ledger(
        client,
        admin_cookie,
        {
            **base_params,
            "account_target_type": "customer_account",
            "account_id": str(source.id),
            "limit": "2",
        },
    )
    second_page = await get_general_ledger(
        client,
        admin_cookie,
        {
            **base_params,
            "account_target_type": "customer_account",
            "account_id": str(source.id),
            "limit": "2",
            "offset": "2",
        },
    )
    assert first_page["entry_count"] == 2
    assert first_page["has_more"] is True
    assert second_page["entry_count"] == 1
    assert second_page["has_more"] is False
    assert entry_ids(first_page) + entry_ids(second_page) == entry_ids(
        full_source_report
    )


async def test_general_ledger_rejects_corrupted_ledger_targets(client: AsyncClient):
    from infrastructure.database import engine

    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        admin = await create_role_user(
            db, f"glx_a_{unique}", RoleChoicesSchema.ADMIN
        )
        corrupt_posted_at = datetime(2099, 1, 1)
        transaction = Transaction(
            reference=f"GL-CORRUPT-{uuid.uuid4().hex[:10].upper()}",
            transaction_type=TransactionTypeEnum.DEPOSIT,
            status=TransactionStatusEnum.POSTED,
            amount=Decimal("1.00"),
            fee_amount=Decimal("0.00"),
            total_debit_amount=Decimal("1.00"),
            currency=AccountCurrencyEnum.USD,
            description="Corrupted general ledger target test",
            created_by_user_id=admin.id,
            posted_at=corrupt_posted_at,
        )
        db.add(transaction)
        await db.flush()
        db.add(
            LedgerEntry(
                transaction_id=transaction.id,
                entry_type=LedgerEntryTypeEnum.DEBIT,
                amount=Decimal("1.00"),
                currency=AccountCurrencyEnum.USD,
                balance_after=Decimal("1.00"),
            )
        )
        await db.commit()

    admin_cookie = await login_and_get_cookie(client, admin.email)
    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.get(
        "/api/v1/admin/reports/general-ledger",
        params={
            "currency": AccountCurrencyEnum.USD.value,
            "from_date": date(2099, 1, 1).isoformat(),
            "to_date": date(2099, 1, 1).isoformat(),
        },
    )
    assert resp.status_code == 500
    assert "exactly one account target" in resp.json()["detail"]
