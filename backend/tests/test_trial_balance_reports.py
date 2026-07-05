import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.accounts.enums import AccountCurrencyEnum, AccountStatusEnum, AccountTypeEnum
from modules.accounts.models import BankAccount
from modules.auth.services import auth_service
from modules.transactions.enums import (
    LedgerEntryTypeEnum,
    TransactionStatusEnum,
    TransactionTypeEnum,
)
from modules.transactions.models import LedgerEntry, Transaction
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
    account_name: str = "Trial Balance Account",
) -> BankAccount:
    account = BankAccount(
        user_id=user_id,
        account_number=f"TB{uuid.uuid4().hex[:8].upper()}",
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


async def post_deposit(
    client: AsyncClient,
    cookie: dict[str, str],
    account_id: uuid.UUID,
    amount: str,
    description: str = "Trial balance deposit",
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
            "description": "Trial balance withdrawal",
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
            "description": "Trial balance transfer",
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
            "description": "Trial balance interest",
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
        json={"reason": "Trial balance reversal"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def get_trial_balance(
    client: AsyncClient,
    cookie: dict[str, str],
    currency: AccountCurrencyEnum,
    as_of: date | None = None,
) -> dict:
    client.cookies.clear()
    client.cookies.update(cookie)
    params: dict[str, str] = {"currency": currency.value}
    if as_of is not None:
        params["as_of"] = as_of.isoformat()
    resp = await client.get("/api/v1/admin/reports/trial-balance", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def line_by_account_id(report: dict, account_id: uuid.UUID) -> dict | None:
    return next(
        (line for line in report["lines"] if line["account_id"] == str(account_id)),
        None,
    )


def line_by_account_code(report: dict, account_code: str) -> dict | None:
    return next(
        (line for line in report["lines"] if line["account_code"] == account_code),
        None,
    )


async def test_trial_balance_auth_rbac_missing_currency_and_empty_report(
    client: AsyncClient,
):
    from infrastructure.database import engine

    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(
            db, f"tb_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        teller = await create_role_user(
            db, f"tb_t_{unique}", RoleChoicesSchema.TELLER
        )
        account_exec = await create_role_user(
            db, f"tb_ae_{unique}", RoleChoicesSchema.ACCOUNT_EXECUTIVE
        )
        branch_manager = await create_role_user(
            db, f"tb_bm_{unique}", RoleChoicesSchema.BRANCH_MANAGER
        )
        admin = await create_role_user(
            db, f"tb_ad_{unique}", RoleChoicesSchema.ADMIN
        )
        super_admin = await create_role_user(
            db, f"tb_sa_{unique}", RoleChoicesSchema.SUPER_ADMIN
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
    resp = await client.get(
        "/api/v1/admin/reports/trial-balance",
        params={"currency": AccountCurrencyEnum.GBP.value},
    )
    assert resp.status_code == 401

    for role_name in ("customer", "teller", "account_exec"):
        client.cookies.clear()
        client.cookies.update(cookies[role_name])
        resp = await client.get(
            "/api/v1/admin/reports/trial-balance",
            params={"currency": AccountCurrencyEnum.GBP.value},
        )
        assert resp.status_code == 403

    client.cookies.clear()
    client.cookies.update(cookies["admin"])
    resp = await client.get("/api/v1/admin/reports/trial-balance")
    assert resp.status_code == 422

    for role_name in ("branch_manager", "admin", "super_admin"):
        report = await get_trial_balance(
            client, cookies[role_name], AccountCurrencyEnum.GBP
        )
        assert report["currency"] == AccountCurrencyEnum.GBP.value
        assert Decimal(report["total_debit"]) == Decimal("0.00")
        assert Decimal(report["total_credit"]) == Decimal("0.00")
        assert Decimal(report["total_net_debit"]) == Decimal("0.00")
        assert Decimal(report["total_net_credit"]) == Decimal("0.00")
        assert report["is_balanced"] is True
        assert report["line_count"] == 0
        assert report["lines"] == []


async def test_trial_balance_reports_postings_reversals_and_currency_filter(
    client: AsyncClient,
):
    from infrastructure.database import engine

    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(
            db, f"tbp_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        admin = await create_role_user(
            db, f"tbp_a_{unique}", RoleChoicesSchema.ADMIN
        )
        source = await create_active_account(
            db, customer.id, Decimal("0.00"), AccountCurrencyEnum.USD, "Source"
        )
        destination = await create_active_account(
            db, customer.id, Decimal("0.00"), AccountCurrencyEnum.USD, "Destination"
        )
        reversed_account = await create_active_account(
            db, customer.id, Decimal("0.00"), AccountCurrencyEnum.USD, "Reversed"
        )
        eur_account = await create_active_account(
            db, customer.id, Decimal("0.00"), AccountCurrencyEnum.EUR, "EUR"
        )

    admin_cookie = await login_and_get_cookie(client, admin.email)
    customer_cookie = await login_and_get_cookie(client, customer.email)

    await post_deposit(client, admin_cookie, source.id, "500.00")
    await post_withdrawal(client, admin_cookie, source.id, "100.00")
    await post_transfer(client, customer_cookie, source.id, destination.id, "150.00")
    await post_interest(client, admin_cookie, destination.id, "25.50")

    reversed_deposit = await post_deposit(
        client, admin_cookie, reversed_account.id, "60.00"
    )
    await reverse_transaction(client, admin_cookie, reversed_deposit["id"])

    await post_deposit(client, admin_cookie, eur_account.id, "77.00")

    report = await get_trial_balance(
        client, admin_cookie, AccountCurrencyEnum.USD, date.today()
    )
    assert report["currency"] == AccountCurrencyEnum.USD.value
    assert Decimal(report["total_debit"]) == Decimal("895.50")
    assert Decimal(report["total_credit"]) == Decimal("895.50")
    assert Decimal(report["total_net_debit"]) == Decimal("425.50")
    assert Decimal(report["total_net_credit"]) == Decimal("425.50")
    assert report["is_balanced"] is True
    assert report["line_count"] == 4

    source_line = line_by_account_id(report, source.id)
    assert source_line is not None
    assert source_line["account_target_type"] == "customer_account"
    assert source_line["account_code"] == source.account_number
    assert Decimal(source_line["debit_total"]) == Decimal("250.00")
    assert Decimal(source_line["credit_total"]) == Decimal("500.00")
    assert Decimal(source_line["net_debit"]) == Decimal("0.00")
    assert Decimal(source_line["net_credit"]) == Decimal("250.00")

    destination_line = line_by_account_id(report, destination.id)
    assert destination_line is not None
    assert Decimal(destination_line["debit_total"]) == Decimal("0.00")
    assert Decimal(destination_line["credit_total"]) == Decimal("175.50")
    assert Decimal(destination_line["net_debit"]) == Decimal("0.00")
    assert Decimal(destination_line["net_credit"]) == Decimal("175.50")

    cash_line = line_by_account_code(report, "CASH-USD")
    assert cash_line is not None
    assert cash_line["account_target_type"] == "internal_account"
    assert Decimal(cash_line["debit_total"]) == Decimal("560.00")
    assert Decimal(cash_line["credit_total"]) == Decimal("160.00")
    assert Decimal(cash_line["net_debit"]) == Decimal("400.00")
    assert Decimal(cash_line["net_credit"]) == Decimal("0.00")

    interest_line = line_by_account_code(report, "INTEREST-EXPENSE-USD")
    assert interest_line is not None
    assert Decimal(interest_line["debit_total"]) == Decimal("25.50")
    assert Decimal(interest_line["credit_total"]) == Decimal("0.00")
    assert Decimal(interest_line["net_debit"]) == Decimal("25.50")
    assert Decimal(interest_line["net_credit"]) == Decimal("0.00")

    assert line_by_account_id(report, reversed_account.id) is None
    assert line_by_account_id(report, eur_account.id) is None
    assert all(line["currency"] == AccountCurrencyEnum.USD.value for line in report["lines"])


async def test_trial_balance_rejects_corrupted_ledger_targets(client: AsyncClient):
    from infrastructure.database import engine

    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        admin = await create_role_user(
            db, f"tbc_a_{unique}", RoleChoicesSchema.ADMIN
        )
        transaction = Transaction(
            reference=f"CORRUPT-{uuid.uuid4().hex[:12].upper()}",
            transaction_type=TransactionTypeEnum.DEPOSIT,
            status=TransactionStatusEnum.POSTED,
            amount=Decimal("1.00"),
            fee_amount=Decimal("0.00"),
            total_debit_amount=Decimal("1.00"),
            currency=AccountCurrencyEnum.USD,
            description="Corrupted ledger target test",
            created_by_user_id=admin.id,
            posted_at=datetime.now(timezone.utc).replace(tzinfo=None),
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
        "/api/v1/admin/reports/trial-balance",
        params={"currency": AccountCurrencyEnum.USD.value},
    )
    assert resp.status_code == 500
    assert "exactly one account target" in resp.json()["detail"]
