import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from modules.accounts.enums import AccountCurrencyEnum, AccountStatusEnum, AccountTypeEnum
from modules.accounts.models import BankAccount, InternalAccount
from modules.auth.services import auth_service
from modules.customer_profiles.enums import (
    EmploymentStatusEnum,
    GenderEnum,
    IdentificationTypeEnum,
    KycStatusEnum,
    MaritalStatusEnum,
    SalutationEnum,
)
from modules.customer_profiles.models import CustomerProfile
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


async def create_approved_profile(
    db: AsyncSession, user_id: uuid.UUID
) -> CustomerProfile:
    profile = CustomerProfile(
        user_id=user_id,
        phone_number="+14155552671",
        title=SalutationEnum.MR,
        gender=GenderEnum.MALE,
        date_of_birth=date(1990, 1, 1),
        country_of_birth="US",
        place_of_birth="San Francisco",
        marital_status=MaritalStatusEnum.SINGLE,
        nationality="US",
        identification_type=IdentificationTypeEnum.PASSPORT,
        identification_number=f"P{uuid.uuid4().hex[:8].upper()}",
        id_issue_date=date(2020, 1, 1),
        id_expiry_date=date(2030, 1, 1),
        address="123 Market St",
        city="San Francisco",
        country="US",
        employment_status=EmploymentStatusEnum.EMPLOYED,
        employer_name="Tech Corp",
        employer_address="456 Mission St",
        employer_city="San Francisco",
        employer_country="US",
        annual_income=120000,
        date_of_employment=date(2021, 1, 1),
        id_photo_url="https://example.com/passport.jpg",
        kyc_status=KycStatusEnum.APPROVED,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


async def create_active_account(
    db: AsyncSession,
    user_id: uuid.UUID,
    balance: Decimal = Decimal("1000.00"),
    currency: AccountCurrencyEnum = AccountCurrencyEnum.USD,
) -> BankAccount:
    account = BankAccount(
        user_id=user_id,
        account_number=f"REV{uuid.uuid4().hex[:8].upper()}",
        account_name="Reversal Test Account",
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


async def assert_reversal_entries_are_opposites(
    db: AsyncSession, original_id: uuid.UUID, reversal_id: uuid.UUID
) -> None:
    original_entries = await get_ledger_entries(db, original_id)
    reversal_entries = await get_ledger_entries(db, reversal_id)
    assert len(original_entries) == len(reversal_entries)
    assert_entries_are_balanced(reversal_entries)
    assert_entries_have_single_target(reversal_entries)

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


async def test_admin_can_reverse_deposit_and_restore_balances(client: AsyncClient):
    from infrastructure.database import engine

    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(
            db, f"rev_dep_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        admin = await create_role_user(
            db, f"rev_dep_a_{unique}", RoleChoicesSchema.ADMIN
        )
        await create_approved_profile(db, customer.id)
        account = await create_active_account(db, customer.id, Decimal("1000.00"))
        cash_result = await db.execute(
            select(InternalAccount).where(InternalAccount.account_code == "CASH-USD")
        )
        cash_account = cash_result.scalar_one_or_none()
        cash_baseline = (
            cash_account.balance if cash_account is not None else Decimal("0.00")
        )

    admin_cookie = await login_and_get_cookie(client, admin.email)
    customer_cookie = await login_and_get_cookie(client, customer.email)

    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post(
        "/api/v1/admin/transactions/deposit",
        json={
            "destination_account_id": str(account.id),
            "amount": "500.00",
            "description": "Deposit to reverse",
        },
    )
    assert resp.status_code == 201
    original = resp.json()

    resp = await client.post(
        f"/api/v1/admin/transactions/{original['id']}/reverse",
        json={"reason": "Incorrect cash deposit"},
    )
    assert resp.status_code == 201
    reversal = resp.json()
    assert reversal["transaction_type"] == TransactionTypeEnum.REVERSAL.value
    assert reversal["status"] == TransactionStatusEnum.POSTED.value
    assert reversal["source_account_id"] == str(account.id)
    assert reversal["destination_account_id"] is None
    assert reversal["reversed_transaction_id"] == original["id"]
    assert reversal["reversal_reason"] == "Incorrect cash deposit"

    async with AsyncSession(engine, expire_on_commit=False) as db:
        refreshed_account = await db.get(BankAccount, account.id)
        assert refreshed_account is not None
        assert refreshed_account.available_balance == Decimal("1000.00")
        assert refreshed_account.current_balance == Decimal("1000.00")

        cash_result = await db.execute(
            select(InternalAccount).where(InternalAccount.account_code == "CASH-USD")
        )
        cash_account = cash_result.scalar_one()
        assert cash_account.balance == cash_baseline

        original_txn = await db.get(Transaction, uuid.UUID(original["id"]))
        assert original_txn is not None
        assert original_txn.status == TransactionStatusEnum.REVERSED
        assert original_txn.reversed_by_transaction_id == uuid.UUID(reversal["id"])
        assert original_txn.reversal_reason == "Incorrect cash deposit"
        assert original_txn.reversed_by_user_id == admin.id
        assert original_txn.reversed_at is not None

        await assert_reversal_entries_are_opposites(
            db, uuid.UUID(original["id"]), uuid.UUID(reversal["id"])
        )

    resp = await client.post(
        f"/api/v1/admin/transactions/{original['id']}/reverse",
        json={"reason": "Try again"},
    )
    assert resp.status_code == 400
    assert "posted" in resp.json()["detail"]

    resp = await client.post(
        f"/api/v1/admin/transactions/{reversal['id']}/reverse",
        json={"reason": "Reverse reversal"},
    )
    assert resp.status_code == 400
    assert "Reversal transactions cannot be reversed" in resp.json()["detail"]

    client.cookies.clear()
    client.cookies.update(customer_cookie)
    resp = await client.get("/api/v1/customer/transactions")
    assert resp.status_code == 200
    txn_ids = {txn["id"] for txn in resp.json()}
    assert original["id"] in txn_ids
    assert reversal["id"] in txn_ids

    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.get("/api/v1/admin/transactions")
    assert resp.status_code == 200
    admin_txn_ids = {txn["id"] for txn in resp.json()}
    assert original["id"] in admin_txn_ids
    assert reversal["id"] in admin_txn_ids


async def test_branch_manager_can_reverse_withdrawal(client: AsyncClient):
    from infrastructure.database import engine

    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(
            db, f"rev_wd_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        admin = await create_role_user(
            db, f"rev_wd_a_{unique}", RoleChoicesSchema.ADMIN
        )
        manager = await create_role_user(
            db, f"rev_wd_bm_{unique}", RoleChoicesSchema.BRANCH_MANAGER
        )
        await create_approved_profile(db, customer.id)
        account = await create_active_account(db, customer.id, Decimal("1000.00"))
        cash_result = await db.execute(
            select(InternalAccount).where(InternalAccount.account_code == "CASH-USD")
        )
        cash_account = cash_result.scalar_one_or_none()
        cash_baseline = (
            cash_account.balance if cash_account is not None else Decimal("0.00")
        )

    admin_cookie = await login_and_get_cookie(client, admin.email)
    manager_cookie = await login_and_get_cookie(client, manager.email)

    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post(
        "/api/v1/admin/transactions/withdrawal",
        json={
            "source_account_id": str(account.id),
            "amount": "300.00",
            "description": "Withdrawal to reverse",
        },
    )
    assert resp.status_code == 201
    original = resp.json()

    client.cookies.clear()
    client.cookies.update(manager_cookie)
    resp = await client.post(
        f"/api/v1/admin/transactions/{original['id']}/reverse",
        json={"reason": "Withdrawal entered in error"},
    )
    assert resp.status_code == 201
    reversal = resp.json()
    assert reversal["source_account_id"] is None
    assert reversal["destination_account_id"] == str(account.id)

    async with AsyncSession(engine, expire_on_commit=False) as db:
        refreshed_account = await db.get(BankAccount, account.id)
        assert refreshed_account is not None
        assert refreshed_account.available_balance == Decimal("1000.00")

        cash_result = await db.execute(
            select(InternalAccount).where(InternalAccount.account_code == "CASH-USD")
        )
        cash_account = cash_result.scalar_one()
        assert cash_account.balance == cash_baseline

        original_txn = await db.get(Transaction, uuid.UUID(original["id"]))
        assert original_txn is not None
        assert original_txn.status == TransactionStatusEnum.REVERSED
        assert original_txn.reversed_by_user_id == manager.id

        await assert_reversal_entries_are_opposites(
            db, uuid.UUID(original["id"]), uuid.UUID(reversal["id"])
        )


async def test_admin_can_reverse_transfer(client: AsyncClient):
    from infrastructure.database import engine

    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(
            db, f"rev_tr_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        admin = await create_role_user(
            db, f"rev_tr_a_{unique}", RoleChoicesSchema.ADMIN
        )
        await create_approved_profile(db, customer.id)
        source = await create_active_account(db, customer.id, Decimal("1000.00"))
        destination = await create_active_account(db, customer.id, Decimal("100.00"))

    customer_cookie = await login_and_get_cookie(client, customer.email)
    admin_cookie = await login_and_get_cookie(client, admin.email)

    client.cookies.clear()
    client.cookies.update(customer_cookie)
    resp = await client.post(
        "/api/v1/customer/transactions/transfer",
        json={
            "source_account_id": str(source.id),
            "destination_account_id": str(destination.id),
            "amount": "250.00",
            "description": "Transfer to reverse",
        },
    )
    assert resp.status_code == 201
    original = resp.json()

    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post(
        f"/api/v1/admin/transactions/{original['id']}/reverse",
        json={"reason": "Wrong destination account"},
    )
    assert resp.status_code == 201
    reversal = resp.json()
    assert reversal["source_account_id"] == str(destination.id)
    assert reversal["destination_account_id"] == str(source.id)

    async with AsyncSession(engine, expire_on_commit=False) as db:
        refreshed_source = await db.get(BankAccount, source.id)
        refreshed_destination = await db.get(BankAccount, destination.id)
        assert refreshed_source is not None
        assert refreshed_destination is not None
        assert refreshed_source.available_balance == Decimal("1000.00")
        assert refreshed_destination.available_balance == Decimal("100.00")

        await assert_reversal_entries_are_opposites(
            db, uuid.UUID(original["id"]), uuid.UUID(reversal["id"])
        )


async def test_reversal_validation_failures(client: AsyncClient):
    from infrastructure.database import engine

    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(
            db, f"rev_val_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        admin = await create_role_user(
            db, f"rev_val_a_{unique}", RoleChoicesSchema.ADMIN
        )
        await create_approved_profile(db, customer.id)
        source = await create_active_account(db, customer.id, Decimal("100.00"))
        destination = await create_active_account(db, customer.id, Decimal("0.00"))

    admin_cookie = await login_and_get_cookie(client, admin.email)
    customer_cookie = await login_and_get_cookie(client, customer.email)

    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post(
        "/api/v1/admin/transactions/deposit",
        json={
            "destination_account_id": str(source.id),
            "amount": "500.00",
            "description": "Deposit that will be spent",
        },
    )
    assert resp.status_code == 201
    deposit = resp.json()

    resp = await client.post(
        f"/api/v1/admin/transactions/{deposit['id']}/reverse",
        json={},
    )
    assert resp.status_code == 422

    resp = await client.post(
        f"/api/v1/admin/transactions/{deposit['id']}/reverse",
        json={"reason": "no"},
    )
    assert resp.status_code == 422

    client.cookies.clear()
    client.cookies.update(customer_cookie)
    resp = await client.post(
        "/api/v1/customer/transactions/transfer",
        json={
            "source_account_id": str(source.id),
            "destination_account_id": str(destination.id),
            "amount": "550.00",
            "description": "Spend most of the deposit",
        },
    )
    assert resp.status_code == 201

    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post(
        f"/api/v1/admin/transactions/{deposit['id']}/reverse",
        json={"reason": "Customer already spent funds"},
    )
    assert resp.status_code == 400
    assert "Insufficient funds to reverse transaction" in resp.json()["detail"]

    async with AsyncSession(engine, expire_on_commit=False) as db:
        no_ledger_txn = Transaction(
            reference=f"NOLEDGER-{uuid.uuid4().hex[:12].upper()}",
            transaction_type=TransactionTypeEnum.DEPOSIT,
            status=TransactionStatusEnum.POSTED,
            source_account_id=None,
            destination_account_id=source.id,
            amount=Decimal("10.00"),
            currency=AccountCurrencyEnum.USD,
            description="Missing ledger test",
            created_by_user_id=admin.id,
            posted_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(no_ledger_txn)
        await db.commit()
        await db.refresh(no_ledger_txn)

    resp = await client.post(
        f"/api/v1/admin/transactions/{no_ledger_txn.id}/reverse",
        json={"reason": "No ledger rows"},
    )
    assert resp.status_code == 400
    assert "no ledger entries" in resp.json()["detail"]


async def test_reversal_rbac_permissions(client: AsyncClient):
    from infrastructure.database import engine

    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(
            db, f"rev_rbac_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        teller = await create_role_user(
            db, f"rev_rbac_t_{unique}", RoleChoicesSchema.TELLER
        )
        ae = await create_role_user(
            db, f"rev_rbac_ae_{unique}", RoleChoicesSchema.ACCOUNT_EXECUTIVE
        )
        branch_manager = await create_role_user(
            db, f"rev_rbac_bm_{unique}", RoleChoicesSchema.BRANCH_MANAGER
        )
        admin = await create_role_user(
            db, f"rev_rbac_a_{unique}", RoleChoicesSchema.ADMIN
        )
        super_admin = await create_role_user(
            db, f"rev_rbac_sa_{unique}", RoleChoicesSchema.SUPER_ADMIN
        )
        await create_approved_profile(db, customer.id)
        account = await create_active_account(db, customer.id, Decimal("1000.00"))

    cookies = {
        "customer": await login_and_get_cookie(client, customer.email),
        "teller": await login_and_get_cookie(client, teller.email),
        "ae": await login_and_get_cookie(client, ae.email),
        "branch_manager": await login_and_get_cookie(client, branch_manager.email),
        "admin": await login_and_get_cookie(client, admin.email),
        "super_admin": await login_and_get_cookie(client, super_admin.email),
    }

    async def create_deposit() -> str:
        client.cookies.clear()
        client.cookies.update(cookies["admin"])
        response = await client.post(
            "/api/v1/admin/transactions/deposit",
            json={
                "destination_account_id": str(account.id),
                "amount": "20.00",
                "description": "RBAC reversal seed",
            },
        )
        assert response.status_code == 201
        return str(response.json()["id"])

    for role_name in ("customer", "teller", "ae"):
        transaction_id = await create_deposit()
        client.cookies.clear()
        client.cookies.update(cookies[role_name])
        resp = await client.post(
            f"/api/v1/admin/transactions/{transaction_id}/reverse",
            json={"reason": f"{role_name} should be denied"},
        )
        assert resp.status_code == 403

    for role_name in ("branch_manager", "admin", "super_admin"):
        transaction_id = await create_deposit()
        client.cookies.clear()
        client.cookies.update(cookies[role_name])
        resp = await client.post(
            f"/api/v1/admin/transactions/{transaction_id}/reverse",
            json={"reason": f"{role_name} may reverse"},
        )
        assert resp.status_code == 201
