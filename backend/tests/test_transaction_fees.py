import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
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
from modules.transactions.enums import LedgerEntryTypeEnum, TransactionTypeEnum
from modules.transactions.models import FeeRule, LedgerEntry
from modules.transactions.services import fee_service
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
        "/api/v1/auth/login", json={"email": email, "password": "password123"}
    )
    assert resp.status_code == 200
    token = resp.cookies.get("access_token")
    assert token is not None
    client.cookies.clear()
    return {"access_token": token}


async def create_active_account(
    db: AsyncSession,
    user_id: uuid.UUID,
    currency: AccountCurrencyEnum,
    balance: Decimal,
) -> BankAccount:
    account = BankAccount(
        user_id=user_id,
        account_number=f"FEE{uuid.uuid4().hex[:8].upper()}",
        account_name="Fee Test Account",
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
    fixed_amount: Decimal = Decimal("0.00"),
    percentage_rate: Decimal = Decimal("0.00"),
    min_fee: Decimal = Decimal("0.00"),
    max_fee: Decimal | None = None,
    is_active: bool = True,
) -> FeeRule:
    rule = FeeRule(
        transaction_type=TransactionTypeEnum.TRANSFER,
        currency=currency,
        fixed_amount=fixed_amount,
        percentage_rate=percentage_rate,
        min_fee=min_fee,
        max_fee=max_fee,
        is_active=is_active,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


async def get_account(db: AsyncSession, account_id: uuid.UUID) -> BankAccount:
    result = await db.execute(select(BankAccount).where(BankAccount.id == account_id))
    return result.scalar_one()


async def get_fee_income_account(
    db: AsyncSession, currency: AccountCurrencyEnum
) -> InternalAccount | None:
    result = await db.execute(
        select(InternalAccount).where(
            InternalAccount.account_code == f"FEE-INCOME-{currency.value}"
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


async def test_transfer_without_active_fee_rule_keeps_existing_behavior(
    client: AsyncClient,
):
    from infrastructure.database import engine

    async with AsyncSession(engine, expire_on_commit=False) as db:
        await deactivate_fee_rules(
            db, TransactionTypeEnum.TRANSFER, AccountCurrencyEnum.USD
        )
        customer = await create_role_user(
            db, f"nofee_a_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.CUSTOMER
        )
        recipient = await create_role_user(
            db, f"nofee_b_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.CUSTOMER
        )
        source = await create_active_account(
            db, customer.id, AccountCurrencyEnum.USD, Decimal("1000.00")
        )
        destination = await create_active_account(
            db, recipient.id, AccountCurrencyEnum.USD, Decimal("25.00")
        )

    cookie = await login_and_get_cookie(client, customer.email)
    client.cookies.update(cookie)
    resp = await client.post(
        "/api/v1/customer/transactions/transfer",
        json={
            "source_account_id": str(source.id),
            "destination_account_id": str(destination.id),
            "amount": "100.00",
            "description": "No fee transfer",
        },
    )
    assert resp.status_code == 201
    transaction = resp.json()
    assert Decimal(transaction["amount"]) == Decimal("100.00")
    assert Decimal(transaction["fee_amount"]) == Decimal("0.00")
    assert Decimal(transaction["total_debit_amount"]) == Decimal("100.00")

    async with AsyncSession(engine, expire_on_commit=False) as db:
        source_after = await get_account(db, source.id)
        destination_after = await get_account(db, destination.id)
        assert source_after.available_balance == Decimal("900.00")
        assert destination_after.available_balance == Decimal("125.00")

        entries = await get_ledger_entries(db, uuid.UUID(transaction["id"]))
        assert len(entries) == 2
        assert_entries_are_balanced(entries)
        assert all(entry.internal_account_id is None for entry in entries)

        debit = next(
            entry for entry in entries if entry.entry_type == LedgerEntryTypeEnum.DEBIT
        )
        credit = next(
            entry for entry in entries if entry.entry_type == LedgerEntryTypeEnum.CREDIT
        )
        assert debit.customer_account_id == source.id
        assert debit.amount == Decimal("100.00")
        assert credit.customer_account_id == destination.id
        assert credit.amount == Decimal("100.00")


async def test_fixed_fee_posts_fee_income_and_ignores_inactive_duplicate(
    client: AsyncClient,
):
    from infrastructure.database import engine

    currency = AccountCurrencyEnum.DKK
    async with AsyncSession(engine, expire_on_commit=False) as db:
        await deactivate_fee_rules(db, TransactionTypeEnum.TRANSFER, currency)
        await create_fee_rule(db, currency, fixed_amount=Decimal("2.00"))
        await create_fee_rule(
            db, currency, fixed_amount=Decimal("999.00"), is_active=False
        )

        customer = await create_role_user(
            db, f"fixed_a_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.CUSTOMER
        )
        recipient = await create_role_user(
            db, f"fixed_b_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.CUSTOMER
        )
        source = await create_active_account(
            db, customer.id, currency, Decimal("1000.00")
        )
        destination = await create_active_account(
            db, recipient.id, currency, Decimal("50.00")
        )
        existing_fee_account = await get_fee_income_account(db, currency)
        fee_baseline = (
            existing_fee_account.balance
            if existing_fee_account is not None
            else Decimal("0.00")
        )

    cookie = await login_and_get_cookie(client, customer.email)
    client.cookies.update(cookie)
    resp = await client.post(
        "/api/v1/customer/transactions/transfer",
        json={
            "source_account_id": str(source.id),
            "destination_account_id": str(destination.id),
            "amount": "100.00",
            "description": "Fixed fee transfer",
        },
    )
    assert resp.status_code == 201
    first_transaction = resp.json()
    assert Decimal(first_transaction["fee_amount"]) == Decimal("2.00")
    assert Decimal(first_transaction["total_debit_amount"]) == Decimal("102.00")

    async with AsyncSession(engine, expire_on_commit=False) as db:
        source_after = await get_account(db, source.id)
        destination_after = await get_account(db, destination.id)
        fee_account = await get_fee_income_account(db, currency)
        assert fee_account is not None
        assert fee_account.account_type == InternalAccountTypeEnum.FEE_INCOME
        assert fee_account.currency == currency
        assert source_after.available_balance == Decimal("898.00")
        assert destination_after.available_balance == Decimal("150.00")
        assert fee_account.balance == fee_baseline + Decimal("2.00")

        first_entries = await get_ledger_entries(
            db, uuid.UUID(first_transaction["id"])
        )
        assert len(first_entries) == 3
        assert_entries_are_balanced(first_entries)
        assert any(
            entry.customer_account_id == source.id
            and entry.entry_type == LedgerEntryTypeEnum.DEBIT
            and entry.amount == Decimal("102.00")
            for entry in first_entries
        )
        assert any(
            entry.customer_account_id == destination.id
            and entry.entry_type == LedgerEntryTypeEnum.CREDIT
            and entry.amount == Decimal("100.00")
            for entry in first_entries
        )
        assert any(
            entry.internal_account_id == fee_account.id
            and entry.entry_type == LedgerEntryTypeEnum.CREDIT
            and entry.amount == Decimal("2.00")
            and entry.balance_after == fee_baseline + Decimal("2.00")
            for entry in first_entries
        )

    resp = await client.post(
        "/api/v1/customer/transactions/transfer",
        json={
            "source_account_id": str(source.id),
            "destination_account_id": str(destination.id),
            "amount": "50.00",
            "description": "Fixed fee reuse transfer",
        },
    )
    assert resp.status_code == 201
    second_transaction = resp.json()

    async with AsyncSession(engine, expire_on_commit=False) as db:
        fee_accounts = list(
            (
                await db.execute(
                    select(InternalAccount).where(
                        InternalAccount.account_code == f"FEE-INCOME-{currency.value}"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(fee_accounts) == 1
        assert fee_accounts[0].balance == fee_baseline + Decimal("4.00")

        second_entries = await get_ledger_entries(
            db, uuid.UUID(second_transaction["id"])
        )
        fee_entry = next(
            entry for entry in second_entries if entry.internal_account_id is not None
        )
        assert fee_entry.internal_account_id == fee_accounts[0].id
        assert fee_entry.amount == Decimal("2.00")


async def test_percentage_fee_rounding_min_max_and_currency_specificity(
    client: AsyncClient,
):
    from infrastructure.database import engine

    currency = AccountCurrencyEnum.GBP
    async with AsyncSession(engine, expire_on_commit=False) as db:
        await deactivate_fee_rules(db, TransactionTypeEnum.TRANSFER, currency)
        await create_fee_rule(
            db, currency, percentage_rate=Decimal("0.010000")
        )
        customer = await create_role_user(
            db, f"pct_a_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.CUSTOMER
        )
        recipient = await create_role_user(
            db, f"pct_b_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.CUSTOMER
        )
        source = await create_active_account(
            db, customer.id, currency, Decimal("1000.00")
        )
        destination = await create_active_account(
            db, recipient.id, currency, Decimal("0.00")
        )
        existing_fee_account = await get_fee_income_account(db, currency)
        fee_baseline = (
            existing_fee_account.balance
            if existing_fee_account is not None
            else Decimal("0.00")
        )

    cookie = await login_and_get_cookie(client, customer.email)
    client.cookies.update(cookie)
    resp = await client.post(
        "/api/v1/customer/transactions/transfer",
        json={
            "source_account_id": str(source.id),
            "destination_account_id": str(destination.id),
            "amount": "100.50",
            "description": "Percentage fee transfer",
        },
    )
    assert resp.status_code == 201
    transaction = resp.json()
    assert Decimal(transaction["fee_amount"]) == Decimal("1.01")
    assert Decimal(transaction["total_debit_amount"]) == Decimal("101.51")

    async with AsyncSession(engine, expire_on_commit=False) as db:
        source_after = await get_account(db, source.id)
        destination_after = await get_account(db, destination.id)
        fee_account = await get_fee_income_account(db, currency)
        assert fee_account is not None
        assert fee_account.account_code == "FEE-INCOME-GBP"
        assert fee_account.currency == AccountCurrencyEnum.GBP
        assert source_after.available_balance == Decimal("898.49")
        assert destination_after.available_balance == Decimal("100.50")
        assert fee_account.balance == fee_baseline + Decimal("1.01")

        await deactivate_fee_rules(db, TransactionTypeEnum.TRANSFER, currency)
        await create_fee_rule(
            db,
            currency,
            percentage_rate=Decimal("0.001000"),
            min_fee=Decimal("1.50"),
        )
        assert (
            await fee_service.calculate_fee(
                db,
                TransactionTypeEnum.TRANSFER,
                currency,
                Decimal("100.00"),
            )
            == Decimal("1.50")
        )

        await deactivate_fee_rules(db, TransactionTypeEnum.TRANSFER, currency)
        await create_fee_rule(
            db,
            currency,
            percentage_rate=Decimal("0.200000"),
            max_fee=Decimal("5.00"),
        )
        assert (
            await fee_service.calculate_fee(
                db,
                TransactionTypeEnum.TRANSFER,
                currency,
                Decimal("100.00"),
            )
            == Decimal("5.00")
        )


async def test_multiple_active_fee_rules_fail_deterministically():
    from infrastructure.database import engine

    currency = AccountCurrencyEnum.EUR
    async with AsyncSession(engine, expire_on_commit=False) as db:
        await deactivate_fee_rules(db, TransactionTypeEnum.TRANSFER, currency)
        await create_fee_rule(db, currency, fixed_amount=Decimal("1.00"))
        await create_fee_rule(db, currency, fixed_amount=Decimal("2.00"))

        with pytest.raises(HTTPException) as exc_info:
            await fee_service.calculate_fee(
                db,
                TransactionTypeEnum.TRANSFER,
                currency,
                Decimal("100.00"),
            )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Multiple active fee rules found"


async def test_transfer_rejects_insufficient_funds_including_fee(
    client: AsyncClient,
):
    from infrastructure.database import engine

    currency = AccountCurrencyEnum.DKK
    async with AsyncSession(engine, expire_on_commit=False) as db:
        await deactivate_fee_rules(db, TransactionTypeEnum.TRANSFER, currency)
        await create_fee_rule(db, currency, fixed_amount=Decimal("1.00"))
        customer = await create_role_user(
            db, f"insuff_a_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.CUSTOMER
        )
        recipient = await create_role_user(
            db, f"insuff_b_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.CUSTOMER
        )
        source = await create_active_account(
            db, customer.id, currency, Decimal("100.00")
        )
        destination = await create_active_account(
            db, recipient.id, currency, Decimal("0.00")
        )

    cookie = await login_and_get_cookie(client, customer.email)
    client.cookies.update(cookie)
    resp = await client.post(
        "/api/v1/customer/transactions/transfer",
        json={
            "source_account_id": str(source.id),
            "destination_account_id": str(destination.id),
            "amount": "100.00",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Insufficient funds including fee"


async def test_reversal_of_fee_bearing_transfer_restores_all_balances(
    client: AsyncClient,
):
    from infrastructure.database import engine

    currency = AccountCurrencyEnum.DKK
    async with AsyncSession(engine, expire_on_commit=False) as db:
        await deactivate_fee_rules(db, TransactionTypeEnum.TRANSFER, currency)
        await create_fee_rule(db, currency, fixed_amount=Decimal("2.00"))
        customer = await create_role_user(
            db, f"revfee_a_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.CUSTOMER
        )
        recipient = await create_role_user(
            db, f"revfee_b_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.CUSTOMER
        )
        admin = await create_role_user(
            db, f"revfee_admin_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.ADMIN
        )
        source = await create_active_account(
            db, customer.id, currency, Decimal("1000.00")
        )
        destination = await create_active_account(
            db, recipient.id, currency, Decimal("50.00")
        )
        existing_fee_account = await get_fee_income_account(db, currency)
        fee_baseline = (
            existing_fee_account.balance
            if existing_fee_account is not None
            else Decimal("0.00")
        )

    customer_cookie = await login_and_get_cookie(client, customer.email)
    client.cookies.update(customer_cookie)
    resp = await client.post(
        "/api/v1/customer/transactions/transfer",
        json={
            "source_account_id": str(source.id),
            "destination_account_id": str(destination.id),
            "amount": "100.00",
            "description": "Fee-bearing transfer",
        },
    )
    assert resp.status_code == 201
    original = resp.json()
    assert Decimal(original["fee_amount"]) == Decimal("2.00")
    assert Decimal(original["total_debit_amount"]) == Decimal("102.00")

    admin_cookie = await login_and_get_cookie(client, admin.email)
    client.cookies.update(admin_cookie)
    resp = await client.post(
        f"/api/v1/admin/transactions/{original['id']}/reverse",
        json={"reason": "Reverse fee-bearing transfer"},
    )
    assert resp.status_code == 201
    reversal = resp.json()
    assert reversal["transaction_type"] == "reversal"
    assert Decimal(reversal["fee_amount"]) == Decimal("2.00")
    assert Decimal(reversal["total_debit_amount"]) == Decimal("102.00")
    assert reversal["reversed_transaction_id"] == original["id"]

    async with AsyncSession(engine, expire_on_commit=False) as db:
        source_after = await get_account(db, source.id)
        destination_after = await get_account(db, destination.id)
        fee_account = await get_fee_income_account(db, currency)
        assert fee_account is not None
        assert source_after.available_balance == Decimal("1000.00")
        assert destination_after.available_balance == Decimal("50.00")
        assert fee_account.balance == fee_baseline

        original_entries = await get_ledger_entries(db, uuid.UUID(original["id"]))
        reversal_entries = await get_ledger_entries(db, uuid.UUID(reversal["id"]))
        assert len(original_entries) == 3
        assert len(reversal_entries) == 3
        assert_entries_are_balanced(original_entries)
        assert_entries_are_balanced(reversal_entries)

        assert any(
            entry.customer_account_id == source.id
            and entry.entry_type == LedgerEntryTypeEnum.DEBIT
            and entry.amount == Decimal("102.00")
            for entry in original_entries
        )
        assert any(
            entry.customer_account_id == source.id
            and entry.entry_type == LedgerEntryTypeEnum.CREDIT
            and entry.amount == Decimal("102.00")
            for entry in reversal_entries
        )
        assert any(
            entry.customer_account_id == destination.id
            and entry.entry_type == LedgerEntryTypeEnum.CREDIT
            and entry.amount == Decimal("100.00")
            for entry in original_entries
        )
        assert any(
            entry.customer_account_id == destination.id
            and entry.entry_type == LedgerEntryTypeEnum.DEBIT
            and entry.amount == Decimal("100.00")
            for entry in reversal_entries
        )
        assert any(
            entry.internal_account_id == fee_account.id
            and entry.entry_type == LedgerEntryTypeEnum.CREDIT
            and entry.amount == Decimal("2.00")
            for entry in original_entries
        )
        assert any(
            entry.internal_account_id == fee_account.id
            and entry.entry_type == LedgerEntryTypeEnum.DEBIT
            and entry.amount == Decimal("2.00")
            for entry in reversal_entries
        )
