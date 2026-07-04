import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.accounts.enums import AccountCurrencyEnum, AccountStatusEnum, AccountTypeEnum
from modules.accounts.models import BankAccount
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
from modules.transactions.enums import LedgerEntryTypeEnum, TransactionTypeEnum
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
        account_number=f"LEA{uuid.uuid4().hex[:8].upper()}",
        account_name="Ledger API Test Account",
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


def assert_entries_are_balanced(entries: list[dict]) -> None:
    total_debit = sum(
        Decimal(entry["amount"])
        for entry in entries
        if entry["entry_type"] == LedgerEntryTypeEnum.DEBIT.value
    )
    total_credit = sum(
        Decimal(entry["amount"])
        for entry in entries
        if entry["entry_type"] == LedgerEntryTypeEnum.CREDIT.value
    )
    assert total_debit == total_credit


def assert_entries_have_single_target(entries: list[dict]) -> None:
    for entry in entries:
        assert (entry["customer_account_id"] is not None) != (
            entry["internal_account_id"] is not None
        )


def assert_opposite_entries(original: list[dict], reversal: list[dict]) -> None:
    assert len(original) == len(reversal)
    unmatched = reversal.copy()
    for original_entry in original:
        expected_type = (
            LedgerEntryTypeEnum.CREDIT.value
            if original_entry["entry_type"] == LedgerEntryTypeEnum.DEBIT.value
            else LedgerEntryTypeEnum.DEBIT.value
        )
        match = next(
            (
                entry
                for entry in unmatched
                if entry["customer_account_id"] == original_entry["customer_account_id"]
                and entry["internal_account_id"] == original_entry["internal_account_id"]
                and entry["amount"] == original_entry["amount"]
                and entry["currency"] == original_entry["currency"]
                and entry["entry_type"] == expected_type
            ),
            None,
        )
        assert match is not None
        unmatched.remove(match)
    assert unmatched == []


async def test_customer_and_admin_can_read_transaction_ledger_entries(
    client: AsyncClient,
):
    from infrastructure.database import engine

    unique = uuid.uuid4().hex[:6]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer_a = await create_role_user(
            db, f"lea_ca_{unique}", RoleChoicesSchema.CUSTOMER
        )
        customer_b = await create_role_user(
            db, f"lea_cb_{unique}", RoleChoicesSchema.CUSTOMER
        )
        teller = await create_role_user(
            db, f"lea_t_{unique}", RoleChoicesSchema.TELLER
        )
        admin = await create_role_user(
            db, f"lea_a_{unique}", RoleChoicesSchema.ADMIN
        )
        await create_approved_profile(db, customer_a.id)
        await create_approved_profile(db, customer_b.id)
        account_a1 = await create_active_account(
            db, customer_a.id, Decimal("1000.00")
        )
        account_a2 = await create_active_account(
            db, customer_a.id, Decimal("500.00")
        )
        account_b = await create_active_account(
            db, customer_b.id, Decimal("200.00")
        )

    customer_a_cookie = await login_and_get_cookie(client, customer_a.email)
    customer_b_cookie = await login_and_get_cookie(client, customer_b.email)
    teller_cookie = await login_and_get_cookie(client, teller.email)
    admin_cookie = await login_and_get_cookie(client, admin.email)

    client.cookies.clear()
    resp = await client.get(
        f"/api/v1/customer/transactions/{uuid.uuid4()}/ledger-entries"
    )
    assert resp.status_code == 401

    resp = await client.get(
        f"/api/v1/admin/transactions/{uuid.uuid4()}/ledger-entries"
    )
    assert resp.status_code == 401

    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post(
        "/api/v1/admin/transactions/deposit",
        json={
            "destination_account_id": str(account_a1.id),
            "amount": "300.00",
            "description": "Ledger API deposit",
        },
    )
    assert resp.status_code == 201
    deposit = resp.json()

    resp = await client.post(
        "/api/v1/admin/transactions/withdrawal",
        json={
            "source_account_id": str(account_a1.id),
            "amount": "100.00",
            "description": "Ledger API withdrawal",
        },
    )
    assert resp.status_code == 201
    withdrawal = resp.json()

    client.cookies.clear()
    client.cookies.update(customer_a_cookie)
    resp = await client.post(
        "/api/v1/customer/transactions/transfer",
        json={
            "source_account_id": str(account_a1.id),
            "destination_account_id": str(account_a2.id),
            "amount": "150.00",
            "description": "Ledger API transfer",
        },
    )
    assert resp.status_code == 201
    transfer = resp.json()

    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post(
        f"/api/v1/admin/transactions/{transfer['id']}/reverse",
        json={"reason": "Ledger API reversal"},
    )
    assert resp.status_code == 201
    reversal = resp.json()
    assert reversal["transaction_type"] == TransactionTypeEnum.REVERSAL.value

    client.cookies.clear()
    client.cookies.update(customer_a_cookie)
    resp = await client.get(
        f"/api/v1/customer/transactions/{deposit['id']}/ledger-entries"
    )
    assert resp.status_code == 200
    deposit_entries = resp.json()
    assert len(deposit_entries) == 2
    assert_entries_are_balanced(deposit_entries)
    assert_entries_have_single_target(deposit_entries)
    assert any(entry["internal_account_id"] for entry in deposit_entries)
    assert any(
        entry["customer_account_id"] == str(account_a1.id)
        and entry["entry_type"] == LedgerEntryTypeEnum.CREDIT.value
        for entry in deposit_entries
    )

    resp = await client.get(
        f"/api/v1/customer/transactions/{withdrawal['id']}/ledger-entries"
    )
    assert resp.status_code == 200
    withdrawal_entries = resp.json()
    assert len(withdrawal_entries) == 2
    assert_entries_are_balanced(withdrawal_entries)
    assert_entries_have_single_target(withdrawal_entries)
    assert any(entry["internal_account_id"] for entry in withdrawal_entries)
    assert any(
        entry["customer_account_id"] == str(account_a1.id)
        and entry["entry_type"] == LedgerEntryTypeEnum.DEBIT.value
        for entry in withdrawal_entries
    )

    resp = await client.get(
        f"/api/v1/customer/transactions/{transfer['id']}/ledger-entries"
    )
    assert resp.status_code == 200
    transfer_entries = resp.json()
    assert len(transfer_entries) == 2
    assert_entries_are_balanced(transfer_entries)
    assert_entries_have_single_target(transfer_entries)
    assert all(entry["customer_account_id"] for entry in transfer_entries)
    assert all(entry["internal_account_id"] is None for entry in transfer_entries)

    resp = await client.get(
        f"/api/v1/customer/transactions/{reversal['id']}/ledger-entries"
    )
    assert resp.status_code == 200
    reversal_entries = resp.json()
    assert_entries_are_balanced(reversal_entries)
    assert_entries_have_single_target(reversal_entries)
    assert_opposite_entries(transfer_entries, reversal_entries)

    client.cookies.clear()
    client.cookies.update(customer_b_cookie)
    resp = await client.get(
        f"/api/v1/customer/transactions/{deposit['id']}/ledger-entries"
    )
    assert resp.status_code == 404

    resp = await client.get(
        f"/api/v1/customer/transactions/{uuid.uuid4()}/ledger-entries"
    )
    assert resp.status_code == 404

    client.cookies.clear()
    client.cookies.update(teller_cookie)
    resp = await client.get(
        f"/api/v1/admin/transactions/{deposit['id']}/ledger-entries"
    )
    assert resp.status_code == 200
    assert resp.json() == deposit_entries

    resp = await client.get(
        f"/api/v1/admin/transactions/{uuid.uuid4()}/ledger-entries"
    )
    assert resp.status_code == 404

    client.cookies.clear()
    client.cookies.update(customer_a_cookie)
    resp = await client.get(
        f"/api/v1/admin/transactions/{deposit['id']}/ledger-entries"
    )
    assert resp.status_code == 403

    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post(
        "/api/v1/admin/transactions/deposit",
        json={
            "destination_account_id": str(account_b.id),
            "amount": "25.00",
            "description": "Other customer deposit",
        },
    )
    assert resp.status_code == 201
    other_customer_deposit = resp.json()

    resp = await client.get(
        f"/api/v1/admin/transactions/{other_customer_deposit['id']}/ledger-entries"
    )
    assert resp.status_code == 200
    other_entries = resp.json()
    assert len(other_entries) == 2
    assert_entries_are_balanced(other_entries)
