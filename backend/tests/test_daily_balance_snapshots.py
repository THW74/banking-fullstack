import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from modules.accounts.enums import AccountCurrencyEnum, AccountStatusEnum, AccountTypeEnum
from modules.accounts.models import BankAccount
from modules.auth.services import auth_service
from modules.daily_balance_snapshots.models import DailyBalanceSnapshot
from modules.transactions.enums import TransactionTypeEnum
from modules.transactions.models import FeeRule, Transaction
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
    currency: AccountCurrencyEnum = AccountCurrencyEnum.USD,
    account_name: str = "Daily Balance Account",
) -> BankAccount:
    account = BankAccount(
        user_id=user_id,
        account_number=f"DBS{uuid.uuid4().hex[:8].upper()}",
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
            "description": "Daily balance deposit",
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
            "description": "Daily balance withdrawal",
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
            "description": "Daily balance transfer",
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
            "description": "Daily balance interest",
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
        json={"reason": "Daily balance reversal"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def generate_snapshots(
    client: AsyncClient,
    cookie: dict[str, str],
    payload: dict[str, str],
) -> list[dict]:
    client.cookies.clear()
    client.cookies.update(cookie)
    resp = await client.post("/api/v1/admin/daily-balance-snapshots", json=payload)
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


def snapshot_by_account_id(snapshots: list[dict], account_id: uuid.UUID) -> dict:
    return next(
        snapshot
        for snapshot in snapshots
        if snapshot["account_id"] == str(account_id)
    )


async def test_daily_balance_snapshot_rbac_empty_day_and_idempotency(
    client: AsyncClient,
):
    from infrastructure.database import engine

    business_date = date(2099, 7, 1)
    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(
            db, f"dbs_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        teller = await create_role_user(
            db, f"dbs_t_{unique}", RoleChoicesSchema.TELLER
        )
        account_exec = await create_role_user(
            db, f"dbs_ae_{unique}", RoleChoicesSchema.ACCOUNT_EXECUTIVE
        )
        branch_manager = await create_role_user(
            db, f"dbs_bm_{unique}", RoleChoicesSchema.BRANCH_MANAGER
        )
        admin = await create_role_user(
            db, f"dbs_a_{unique}", RoleChoicesSchema.ADMIN
        )
        account = await create_active_account(
            db,
            customer.id,
            Decimal("123.45"),
            AccountCurrencyEnum.USD,
            "Empty Day Snapshot",
        )

    cookies = {
        "customer": await login_and_get_cookie(client, customer.email),
        "teller": await login_and_get_cookie(client, teller.email),
        "account_exec": await login_and_get_cookie(client, account_exec.email),
        "branch_manager": await login_and_get_cookie(client, branch_manager.email),
        "admin": await login_and_get_cookie(client, admin.email),
    }
    payload = {
        "business_date": business_date.isoformat(),
        "account_id": str(account.id),
    }

    client.cookies.clear()
    resp = await client.get("/api/v1/admin/daily-balance-snapshots")
    assert resp.status_code == 401
    resp = await client.post("/api/v1/admin/daily-balance-snapshots", json=payload)
    assert resp.status_code == 401

    for role_name in ("customer", "teller", "account_exec"):
        client.cookies.clear()
        client.cookies.update(cookies[role_name])
        resp = await client.get(
            "/api/v1/admin/daily-balance-snapshots",
            params={
                "business_date": business_date.isoformat(),
                "account_id": str(account.id),
            },
        )
        assert resp.status_code == 403

        resp = await client.post(
            "/api/v1/admin/daily-balance-snapshots", json=payload
        )
        assert resp.status_code == 403

    client.cookies.clear()
    client.cookies.update(cookies["branch_manager"])
    resp = await client.get(
        "/api/v1/admin/daily-balance-snapshots",
        params={
            "business_date": business_date.isoformat(),
            "account_id": str(account.id),
        },
    )
    assert resp.status_code == 200
    assert resp.json() == []

    resp = await client.post("/api/v1/admin/daily-balance-snapshots", json=payload)
    assert resp.status_code == 403

    snapshots = await generate_snapshots(client, cookies["admin"], payload)
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot["business_date"] == business_date.isoformat()
    assert snapshot["account_id"] == str(account.id)
    assert snapshot["currency"] == AccountCurrencyEnum.USD.value
    assert decimal_value(snapshot["opening_balance"]) == Decimal("123.45")
    assert decimal_value(snapshot["closing_balance"]) == Decimal("123.45")
    assert decimal_value(snapshot["available_balance"]) == Decimal("123.45")
    assert decimal_value(snapshot["current_balance"]) == Decimal("123.45")
    assert decimal_value(snapshot["debit_total"]) == Decimal("0.00")
    assert decimal_value(snapshot["credit_total"]) == Decimal("0.00")
    assert snapshot["transaction_count"] == 0

    duplicate = await generate_snapshots(client, cookies["admin"], payload)
    assert duplicate[0]["id"] == snapshot["id"]

    client.cookies.clear()
    client.cookies.update(cookies["branch_manager"])
    resp = await client.get(
        "/api/v1/admin/daily-balance-snapshots",
        params={
            "business_date": business_date.isoformat(),
            "account_id": str(account.id),
        },
    )
    assert resp.status_code == 200
    listed = resp.json()
    assert [item["id"] for item in listed] == [snapshot["id"]]

    resp = await client.get(f"/api/v1/admin/daily-balance-snapshots/{snapshot['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == snapshot["id"]

    async with AsyncSession(engine, expire_on_commit=False) as db:
        result = await db.execute(
            select(DailyBalanceSnapshot).where(
                DailyBalanceSnapshot.business_date == business_date,
                DailyBalanceSnapshot.account_id == account.id,
            )
        )
        assert len(list(result.scalars().all())) == 1


async def test_daily_balance_snapshots_capture_activity_and_currency_separation(
    client: AsyncClient,
):
    from infrastructure.database import engine

    business_date = date(2099, 7, 2)
    currency = AccountCurrencyEnum.GBP
    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        await deactivate_fee_rules(db, TransactionTypeEnum.TRANSFER, currency)
        await create_fee_rule(db, currency, Decimal("2.00"))
        customer = await create_role_user(
            db, f"dbsa_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        admin = await create_role_user(
            db, f"dbsa_a_{unique}", RoleChoicesSchema.ADMIN
        )
        source = await create_active_account(
            db, customer.id, Decimal("1000.00"), currency, "Snapshot Source"
        )
        destination = await create_active_account(
            db, customer.id, Decimal("0.00"), currency, "Snapshot Destination"
        )
        reversed_account = await create_active_account(
            db, customer.id, Decimal("0.00"), currency, "Snapshot Reversed"
        )
        eur_account = await create_active_account(
            db, customer.id, Decimal("0.00"), AccountCurrencyEnum.EUR, "Snapshot EUR"
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

    snapshots = await generate_snapshots(
        client,
        admin_cookie,
        {
            "business_date": business_date.isoformat(),
            "currency": currency.value,
        },
    )
    snapshot_account_ids = {snapshot["account_id"] for snapshot in snapshots}
    assert str(source.id) in snapshot_account_ids
    assert str(destination.id) in snapshot_account_ids
    assert str(reversed_account.id) in snapshot_account_ids
    assert str(eur_account.id) not in snapshot_account_ids

    source_snapshot = snapshot_by_account_id(snapshots, source.id)
    assert decimal_value(source_snapshot["opening_balance"]) == Decimal("1000.00")
    assert decimal_value(source_snapshot["closing_balance"]) == Decimal("1248.00")
    assert decimal_value(source_snapshot["debit_total"]) == Decimal("252.00")
    assert decimal_value(source_snapshot["credit_total"]) == Decimal("500.00")
    assert source_snapshot["transaction_count"] == 3

    destination_snapshot = snapshot_by_account_id(snapshots, destination.id)
    assert decimal_value(destination_snapshot["opening_balance"]) == Decimal("0.00")
    assert decimal_value(destination_snapshot["closing_balance"]) == Decimal("175.50")
    assert decimal_value(destination_snapshot["debit_total"]) == Decimal("0.00")
    assert decimal_value(destination_snapshot["credit_total"]) == Decimal("175.50")
    assert destination_snapshot["transaction_count"] == 2

    reversed_snapshot = snapshot_by_account_id(snapshots, reversed_account.id)
    assert decimal_value(reversed_snapshot["opening_balance"]) == Decimal("0.00")
    assert decimal_value(reversed_snapshot["closing_balance"]) == Decimal("0.00")
    assert decimal_value(reversed_snapshot["debit_total"]) == Decimal("60.00")
    assert decimal_value(reversed_snapshot["credit_total"]) == Decimal("60.00")
    assert reversed_snapshot["transaction_count"] == 2

    eur_snapshots = await generate_snapshots(
        client,
        admin_cookie,
        {
            "business_date": business_date.isoformat(),
            "account_id": str(eur_account.id),
        },
    )
    assert len(eur_snapshots) == 1
    eur_snapshot = eur_snapshots[0]
    assert eur_snapshot["currency"] == AccountCurrencyEnum.EUR.value
    assert decimal_value(eur_snapshot["opening_balance"]) == Decimal("0.00")
    assert decimal_value(eur_snapshot["closing_balance"]) == Decimal("77.00")
    assert decimal_value(eur_snapshot["credit_total"]) == Decimal("77.00")
    assert eur_snapshot["transaction_count"] == 1
