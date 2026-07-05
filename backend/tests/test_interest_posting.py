import uuid
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


async def create_account(
    db: AsyncSession,
    user_id: uuid.UUID,
    balance: Decimal = Decimal("1000.00"),
    currency: AccountCurrencyEnum = AccountCurrencyEnum.USD,
    status: AccountStatusEnum = AccountStatusEnum.ACTIVE,
) -> BankAccount:
    account = BankAccount(
        user_id=user_id,
        account_number=f"INT{uuid.uuid4().hex[:8].upper()}",
        account_name="Interest Posting Account",
        account_type=AccountTypeEnum.SAVINGS,
        currency=currency,
        account_status=status,
        available_balance=balance,
        current_balance=balance,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


async def get_interest_expense_account(
    db: AsyncSession, currency: AccountCurrencyEnum
) -> InternalAccount | None:
    result = await db.execute(
        select(InternalAccount).where(
            InternalAccount.account_code == f"INTEREST-EXPENSE-{currency.value}"
        )
    )
    return result.scalar_one_or_none()


async def get_ledger_entries(
    db: AsyncSession, transaction_id: uuid.UUID
) -> list[LedgerEntry]:
    result = await db.execute(
        select(LedgerEntry).where(LedgerEntry.transaction_id == transaction_id)
    )
    return list(result.scalars().all())


def assert_entries_are_balanced(entries: list[LedgerEntry]) -> None:
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
    assert total_debit == total_credit


def assert_entries_have_single_target(entries: list[LedgerEntry]) -> None:
    for entry in entries:
        assert (entry.customer_account_id is not None) != (
            entry.internal_account_id is not None
        )


def assert_reversal_entries_are_opposites(
    original_entries: list[LedgerEntry], reversal_entries: list[LedgerEntry]
) -> None:
    assert len(original_entries) == len(reversal_entries)
    unmatched = reversal_entries.copy()
    for original in original_entries:
        expected_type = (
            LedgerEntryTypeEnum.CREDIT
            if original.entry_type == LedgerEntryTypeEnum.DEBIT
            else LedgerEntryTypeEnum.DEBIT
        )
        match = next(
            (
                entry
                for entry in unmatched
                if entry.customer_account_id == original.customer_account_id
                and entry.internal_account_id == original.internal_account_id
                and entry.amount == original.amount
                and entry.currency == original.currency
                and entry.entry_type == expected_type
            ),
            None,
        )
        assert match is not None
        unmatched.remove(match)
    assert unmatched == []


async def assert_no_interest_transactions(
    db: AsyncSession, account_id: uuid.UUID
) -> None:
    result = await db.execute(
        select(Transaction).where(
            Transaction.destination_account_id == account_id,
            Transaction.transaction_type == TransactionTypeEnum.INTEREST_POSTING,
        )
    )
    assert list(result.scalars().all()) == []


async def test_admin_can_post_interest_and_reverse_it(client: AsyncClient):
    from infrastructure.database import engine

    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(
            db, f"int_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        admin = await create_role_user(db, f"int_a_{unique}", RoleChoicesSchema.ADMIN)
        account = await create_account(db, customer.id, Decimal("1000.00"))

        existing_interest_account = await get_interest_expense_account(
            db, AccountCurrencyEnum.USD
        )
        interest_baseline = (
            existing_interest_account.balance
            if existing_interest_account is not None
            else Decimal("0.00")
        )

    admin_cookie = await login_and_get_cookie(client, admin.email)

    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post(
        "/api/v1/admin/transactions/interest-posting",
        json={
            "destination_account_id": str(account.id),
            "amount": "25.50",
            "description": "Monthly savings interest",
        },
    )
    assert resp.status_code == 201
    original = resp.json()
    assert original["transaction_type"] == TransactionTypeEnum.INTEREST_POSTING.value
    assert original["status"] == TransactionStatusEnum.POSTED.value
    assert original["source_account_id"] is None
    assert original["destination_account_id"] == str(account.id)
    assert Decimal(original["amount"]) == Decimal("25.50")
    assert Decimal(original["fee_amount"]) == Decimal("0.00")
    assert Decimal(original["total_debit_amount"]) == Decimal("25.50")
    assert original["posted_at"] is not None

    async with AsyncSession(engine, expire_on_commit=False) as db:
        refreshed_account = await db.get(BankAccount, account.id)
        assert refreshed_account is not None
        assert refreshed_account.available_balance == Decimal("1025.50")
        assert refreshed_account.current_balance == Decimal("1025.50")

        interest_account = await get_interest_expense_account(
            db, AccountCurrencyEnum.USD
        )
        assert interest_account is not None
        assert interest_account.account_type == InternalAccountTypeEnum.INTEREST_EXPENSE
        assert interest_account.balance == interest_baseline + Decimal("25.50")

        original_entries = await get_ledger_entries(db, uuid.UUID(original["id"]))
        assert len(original_entries) == 2
        assert_entries_are_balanced(original_entries)
        assert_entries_have_single_target(original_entries)

        debit_entry = next(
            entry
            for entry in original_entries
            if entry.entry_type == LedgerEntryTypeEnum.DEBIT
        )
        credit_entry = next(
            entry
            for entry in original_entries
            if entry.entry_type == LedgerEntryTypeEnum.CREDIT
        )
        assert debit_entry.internal_account_id == interest_account.id
        assert debit_entry.customer_account_id is None
        assert debit_entry.amount == Decimal("25.50")
        assert debit_entry.balance_after == interest_baseline + Decimal("25.50")
        assert credit_entry.customer_account_id == account.id
        assert credit_entry.internal_account_id is None
        assert credit_entry.amount == Decimal("25.50")
        assert credit_entry.balance_after == Decimal("1025.50")

    resp = await client.post(
        f"/api/v1/admin/transactions/{original['id']}/reverse",
        json={"reason": "Interest posted in error"},
    )
    assert resp.status_code == 201
    reversal = resp.json()
    assert reversal["transaction_type"] == TransactionTypeEnum.REVERSAL.value
    assert reversal["source_account_id"] == str(account.id)
    assert reversal["destination_account_id"] is None
    assert reversal["reversed_transaction_id"] == original["id"]

    async with AsyncSession(engine, expire_on_commit=False) as db:
        refreshed_account = await db.get(BankAccount, account.id)
        assert refreshed_account is not None
        assert refreshed_account.available_balance == Decimal("1000.00")
        assert refreshed_account.current_balance == Decimal("1000.00")

        interest_account = await get_interest_expense_account(
            db, AccountCurrencyEnum.USD
        )
        assert interest_account is not None
        assert interest_account.balance == interest_baseline

        original_txn = await db.get(Transaction, uuid.UUID(original["id"]))
        assert original_txn is not None
        assert original_txn.status == TransactionStatusEnum.REVERSED
        assert original_txn.reversed_by_transaction_id == uuid.UUID(reversal["id"])

        original_entries = await get_ledger_entries(db, uuid.UUID(original["id"]))
        reversal_entries = await get_ledger_entries(db, uuid.UUID(reversal["id"]))
        assert_entries_are_balanced(reversal_entries)
        assert_entries_have_single_target(reversal_entries)
        assert_reversal_entries_are_opposites(original_entries, reversal_entries)


async def test_interest_posting_rejects_inactive_account_without_side_effects(
    client: AsyncClient,
):
    from infrastructure.database import engine

    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(
            db, f"int_i_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        admin = await create_role_user(
            db, f"int_i_a_{unique}", RoleChoicesSchema.ADMIN
        )
        account = await create_account(
            db,
            customer.id,
            Decimal("500.00"),
            AccountCurrencyEnum.DKK,
            AccountStatusEnum.FROZEN,
        )

    admin_cookie = await login_and_get_cookie(client, admin.email)

    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post(
        "/api/v1/admin/transactions/interest-posting",
        json={
            "destination_account_id": str(account.id),
            "amount": "10.00",
            "description": "Should fail",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Destination account is not active"

    async with AsyncSession(engine, expire_on_commit=False) as db:
        refreshed_account = await db.get(BankAccount, account.id)
        assert refreshed_account is not None
        assert refreshed_account.available_balance == Decimal("500.00")
        assert refreshed_account.current_balance == Decimal("500.00")
        assert await get_interest_expense_account(db, AccountCurrencyEnum.DKK) is None
        await assert_no_interest_transactions(db, account.id)


async def test_interest_posting_requires_post_transaction_permission(
    client: AsyncClient,
):
    from infrastructure.database import engine

    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(
            db, f"int_r_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        account_exec = await create_role_user(
            db, f"int_r_ae_{unique}", RoleChoicesSchema.ACCOUNT_EXECUTIVE
        )
        account = await create_account(db, customer.id, Decimal("200.00"))

    account_exec_cookie = await login_and_get_cookie(client, account_exec.email)

    client.cookies.clear()
    client.cookies.update(account_exec_cookie)
    resp = await client.post(
        "/api/v1/admin/transactions/interest-posting",
        json={
            "destination_account_id": str(account.id),
            "amount": "12.00",
            "description": "Unauthorized interest posting",
        },
    )
    assert resp.status_code == 403

    async with AsyncSession(engine, expire_on_commit=False) as db:
        refreshed_account = await db.get(BankAccount, account.id)
        assert refreshed_account is not None
        assert refreshed_account.available_balance == Decimal("200.00")
        assert refreshed_account.current_balance == Decimal("200.00")
        await assert_no_interest_transactions(db, account.id)
