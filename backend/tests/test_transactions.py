import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.users.models import User
from modules.users.schemas import RoleChoicesSchema, AccountStatusSchema, SecurityQuestionsSchema
from modules.customer_profiles.enums import (
    KycStatusEnum,
    SalutationEnum,
    GenderEnum,
    MaritalStatusEnum,
    IdentificationTypeEnum,
    EmploymentStatusEnum,
)
from modules.customer_profiles.models import CustomerProfile
from modules.accounts.enums import AccountTypeEnum, AccountCurrencyEnum, AccountStatusEnum
from modules.accounts.models import BankAccount, InternalAccount
from modules.transactions.enums import TransactionTypeEnum, LedgerEntryTypeEnum
from modules.transactions.models import Transaction, LedgerEntry
from modules.transactions.services import transaction_service
from modules.auth.services import auth_service

pytestmark = pytest.mark.asyncio


# --- Helpers ---


async def create_role_user(db: AsyncSession, username: str, role: RoleChoicesSchema) -> User:
    hashed_password = auth_service.get_password_hash("password123")
    user = User(
        username=username,
        email=f"{username}@example.com",
        full_name=f"Full Name {username}",
        id_no=uuid.uuid4().int % 100000000 + 1,
        security_question=SecurityQuestionsSchema.FAVORITE_COLOR,
        security_answer_hash=auth_service.get_password_hash("blue"),
        hashed_password=hashed_password,
        is_active=True,
        is_superuser=(role == RoleChoicesSchema.SUPER_ADMIN),
        account_status=AccountStatusSchema.ACTIVE,
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def login_and_get_cookie(client: AsyncClient, email: str) -> dict:
    client.cookies.clear()
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert resp.status_code == 200
    token = resp.cookies.get("access_token")
    client.cookies.clear()
    return {"access_token": token}


async def create_approved_profile(db: AsyncSession, user_id: uuid.UUID) -> CustomerProfile:
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
        identification_number="P1234567",
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
    currency: AccountCurrencyEnum = AccountCurrencyEnum.USD,
    balance: Decimal = Decimal("1000.00"),
) -> BankAccount:
    account = BankAccount(
        user_id=user_id,
        account_number=f"ACC{uuid.uuid4().hex[:8].upper()}",
        account_name="Test Account",
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
        has_customer = entry.customer_account_id is not None
        has_internal = entry.internal_account_id is not None
        assert has_customer != has_internal


# --- Main test ---


async def test_transactions_scenarios(client: AsyncClient):
    from infrastructure.database import engine

    async with AsyncSession(engine, expire_on_commit=False) as db:
        cust_a = await create_role_user(db, f"ta_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.CUSTOMER)
        cust_b = await create_role_user(db, f"tb_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.CUSTOMER)
        teller = await create_role_user(db, f"tt_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.TELLER)
        ae = await create_role_user(db, f"te_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.ACCOUNT_EXECUTIVE)
        admin = await create_role_user(db, f"td_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.ADMIN)

        # Create approved KYC profiles and active accounts
        await create_approved_profile(db, cust_a.id)
        await create_approved_profile(db, cust_b.id)

        acct_a1 = await create_active_account(db, cust_a.id, AccountCurrencyEnum.USD, Decimal("5000.00"))
        acct_a2 = await create_active_account(db, cust_a.id, AccountCurrencyEnum.USD, Decimal("1000.00"))
        acct_a_eur = await create_active_account(db, cust_a.id, AccountCurrencyEnum.EUR, Decimal("2000.00"))
        acct_b1 = await create_active_account(db, cust_b.id, AccountCurrencyEnum.USD, Decimal("500.00"))

        usd_cash_result = await db.execute(
            select(InternalAccount).where(InternalAccount.account_code == "CASH-USD")
        )
        usd_cash = usd_cash_result.scalar_one_or_none()
        usd_cash_baseline = (
            usd_cash.balance if usd_cash is not None else Decimal("0.00")
        )

        eur_cash_result = await db.execute(
            select(InternalAccount).where(InternalAccount.account_code == "CASH-EUR")
        )
        eur_cash = eur_cash_result.scalar_one_or_none()
        eur_cash_baseline = (
            eur_cash.balance if eur_cash is not None else Decimal("0.00")
        )

    cust_a_cookie = await login_and_get_cookie(client, cust_a.email)
    cust_b_cookie = await login_and_get_cookie(client, cust_b.email)
    teller_cookie = await login_and_get_cookie(client, teller.email)
    ae_cookie = await login_and_get_cookie(client, ae.email)
    admin_cookie = await login_and_get_cookie(client, admin.email)

    # --- 1. Unauthenticated access returns 401 ---
    client.cookies.clear()
    resp = await client.get("/api/v1/customer/transactions")
    assert resp.status_code == 401

    resp = await client.get("/api/v1/admin/transactions")
    assert resp.status_code == 401

    # --- 2. Admin deposit into customer A's account ---
    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post("/api/v1/admin/transactions/deposit", json={
        "destination_account_id": str(acct_a1.id),
        "amount": "500.00",
        "description": "Initial deposit",
    })
    assert resp.status_code == 201
    deposit_txn = resp.json()
    assert deposit_txn["transaction_type"] == "deposit"
    assert deposit_txn["status"] == "posted"
    assert Decimal(deposit_txn["amount"]) == Decimal("500.00")
    assert deposit_txn["source_account_id"] is None
    assert deposit_txn["destination_account_id"] == str(acct_a1.id)
    assert deposit_txn["posted_at"] is not None

    # Verify balance increased (5000 + 500 = 5500)
    client.cookies.clear()
    client.cookies.update(cust_a_cookie)
    resp = await client.get(f"/api/v1/customer/accounts/{acct_a1.id}")
    assert resp.status_code == 200
    assert Decimal(resp.json()["available_balance"]) == Decimal("5500.00")
    assert Decimal(resp.json()["current_balance"]) == Decimal("5500.00")

    # --- 3. Verify deposit created balanced internal DEBIT + customer CREDIT ---
    async with AsyncSession(engine, expire_on_commit=False) as db:
        cash_stmt = select(InternalAccount).where(
            InternalAccount.account_code == "CASH-USD"
        )
        cash_result = await db.execute(cash_stmt)
        cash_account = cash_result.scalar_one()
        assert cash_account.currency == AccountCurrencyEnum.USD
        assert cash_account.balance == usd_cash_baseline + Decimal("500.00")

        entries_stmt = select(LedgerEntry).where(LedgerEntry.transaction_id == uuid.UUID(deposit_txn["id"]))
        entries_result = await db.execute(entries_stmt)
        entries = list(entries_result.scalars().all())
        assert len(entries) == 2
        assert_entries_are_balanced(entries)
        assert_entries_have_single_target(entries)

        debit = [e for e in entries if e.entry_type == LedgerEntryTypeEnum.DEBIT]
        credit = [e for e in entries if e.entry_type == LedgerEntryTypeEnum.CREDIT]
        assert len(debit) == 1
        assert len(credit) == 1
        assert debit[0].amount == credit[0].amount == Decimal("500.00")
        assert debit[0].internal_account_id == cash_account.id
        assert debit[0].customer_account_id is None
        assert debit[0].balance_after == usd_cash_baseline + Decimal("500.00")
        assert credit[0].customer_account_id == acct_a1.id
        assert credit[0].internal_account_id is None
        assert credit[0].balance_after == Decimal("5500.00")

    # Verify settlement accounts are currency-specific.
    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post("/api/v1/admin/transactions/deposit", json={
        "destination_account_id": str(acct_a_eur.id),
        "amount": "25.00",
        "description": "EUR cash settlement seed",
    })
    assert resp.status_code == 201
    async with AsyncSession(engine, expire_on_commit=False) as db:
        cash_stmt = select(InternalAccount).where(
            InternalAccount.account_code == "CASH-EUR"
        )
        cash_result = await db.execute(cash_stmt)
        cash_account = cash_result.scalar_one()
        assert cash_account.currency == AccountCurrencyEnum.EUR
        assert cash_account.balance == eur_cash_baseline + Decimal("25.00")

    # --- 4. Customer A transfers to own account (acct_a1 -> acct_a2) ---
    client.cookies.clear()
    client.cookies.update(cust_a_cookie)
    resp = await client.post("/api/v1/customer/transactions/transfer", json={
        "source_account_id": str(acct_a1.id),
        "destination_account_id": str(acct_a2.id),
        "amount": "1500.00",
        "description": "Self transfer",
    })
    assert resp.status_code == 201
    transfer_txn = resp.json()
    assert transfer_txn["transaction_type"] == "transfer"
    assert transfer_txn["status"] == "posted"
    assert Decimal(transfer_txn["amount"]) == Decimal("1500.00")

    # Verify balances: acct_a1 = 5500 - 1500 = 4000, acct_a2 = 1000 + 1500 = 2500
    resp = await client.get(f"/api/v1/customer/accounts/{acct_a1.id}")
    assert Decimal(resp.json()["available_balance"]) == Decimal("4000.00")
    resp = await client.get(f"/api/v1/customer/accounts/{acct_a2.id}")
    assert Decimal(resp.json()["available_balance"]) == Decimal("2500.00")

    # --- 5. Verify transfer created balanced DEBIT + CREDIT ledger entries ---
    async with AsyncSession(engine, expire_on_commit=False) as db:
        entries_stmt = select(LedgerEntry).where(
            LedgerEntry.transaction_id == uuid.UUID(transfer_txn["id"])
        )
        entries_result = await db.execute(entries_stmt)
        entries = list(entries_result.scalars().all())
        assert len(entries) == 2
        assert_entries_are_balanced(entries)
        assert_entries_have_single_target(entries)
        debit = [e for e in entries if e.entry_type == LedgerEntryTypeEnum.DEBIT]
        credit = [e for e in entries if e.entry_type == LedgerEntryTypeEnum.CREDIT]
        assert len(debit) == 1
        assert len(credit) == 1
        # Total DEBIT must equal total CREDIT
        assert debit[0].amount == credit[0].amount == Decimal("1500.00")
        assert debit[0].customer_account_id == acct_a1.id
        assert debit[0].internal_account_id is None
        assert debit[0].balance_after == Decimal("4000.00")
        assert credit[0].customer_account_id == acct_a2.id
        assert credit[0].internal_account_id is None
        assert credit[0].balance_after == Decimal("2500.00")

    # --- 6. Customer A transfers to customer B's account ---
    resp = await client.post("/api/v1/customer/transactions/transfer", json={
        "source_account_id": str(acct_a1.id),
        "destination_account_id": str(acct_b1.id),
        "amount": "200.00",
        "description": "Payment to B",
    })
    assert resp.status_code == 201

    # acct_a1 = 4000 - 200 = 3800, acct_b1 = 500 + 200 = 700
    resp = await client.get(f"/api/v1/customer/accounts/{acct_a1.id}")
    assert Decimal(resp.json()["available_balance"]) == Decimal("3800.00")
    client.cookies.clear()
    client.cookies.update(cust_b_cookie)
    resp = await client.get(f"/api/v1/customer/accounts/{acct_b1.id}")
    assert Decimal(resp.json()["available_balance"]) == Decimal("700.00")

    # --- 7. Transfer fails: source does not belong to customer ---
    client.cookies.clear()
    client.cookies.update(cust_b_cookie)
    resp = await client.post("/api/v1/customer/transactions/transfer", json={
        "source_account_id": str(acct_a1.id),
        "destination_account_id": str(acct_b1.id),
        "amount": "100.00",
    })
    assert resp.status_code == 403

    # --- 8. Transfer fails: insufficient funds ---
    client.cookies.clear()
    client.cookies.update(cust_a_cookie)
    resp = await client.post("/api/v1/customer/transactions/transfer", json={
        "source_account_id": str(acct_a1.id),
        "destination_account_id": str(acct_a2.id),
        "amount": "999999.00",
    })
    assert resp.status_code == 400
    assert "Insufficient funds" in resp.json()["detail"]

    # --- 9. Transfer fails: same source and destination ---
    resp = await client.post("/api/v1/customer/transactions/transfer", json={
        "source_account_id": str(acct_a1.id),
        "destination_account_id": str(acct_a1.id),
        "amount": "100.00",
    })
    assert resp.status_code == 400

    # --- 10. Transfer fails: currency mismatch ---
    resp = await client.post("/api/v1/customer/transactions/transfer", json={
        "source_account_id": str(acct_a1.id),
        "destination_account_id": str(acct_a_eur.id),
        "amount": "100.00",
    })
    assert resp.status_code == 400
    assert "Currency mismatch" in resp.json()["detail"]

    # --- 11. Transfer fails: frozen account ---
    # Freeze acct_a2 via admin
    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post(f"/api/v1/admin/accounts/{acct_a2.id}/freeze")
    assert resp.status_code == 200

    client.cookies.clear()
    client.cookies.update(cust_a_cookie)
    resp = await client.post("/api/v1/customer/transactions/transfer", json={
        "source_account_id": str(acct_a1.id),
        "destination_account_id": str(acct_a2.id),
        "amount": "100.00",
    })
    assert resp.status_code == 400
    assert "not active" in resp.json()["detail"]

    # Unfreeze for subsequent tests (set back to ACTIVE via direct DB update)
    async with AsyncSession(engine, expire_on_commit=False) as db:
        stmt = select(BankAccount).where(BankAccount.id == acct_a2.id)
        result = await db.execute(stmt)
        acct = result.scalar_one()
        acct.account_status = AccountStatusEnum.ACTIVE
        db.add(acct)
        await db.commit()

    # --- 12. Admin withdrawal ---
    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post("/api/v1/admin/transactions/withdrawal", json={
        "source_account_id": str(acct_a1.id),
        "amount": "300.00",
        "description": "Admin withdrawal",
    })
    assert resp.status_code == 201
    withdrawal_txn = resp.json()
    assert withdrawal_txn["transaction_type"] == "withdrawal"
    assert Decimal(withdrawal_txn["amount"]) == Decimal("300.00")
    assert withdrawal_txn["destination_account_id"] is None

    # acct_a1 = 3800 - 300 = 3500
    client.cookies.clear()
    client.cookies.update(cust_a_cookie)
    resp = await client.get(f"/api/v1/customer/accounts/{acct_a1.id}")
    assert Decimal(resp.json()["available_balance"]) == Decimal("3500.00")

    # --- 13. Verify withdrawal created balanced customer DEBIT + internal CREDIT ---
    async with AsyncSession(engine, expire_on_commit=False) as db:
        cash_stmt = select(InternalAccount).where(
            InternalAccount.account_code == "CASH-USD"
        )
        cash_result = await db.execute(cash_stmt)
        cash_account = cash_result.scalar_one()
        assert cash_account.balance == usd_cash_baseline + Decimal("200.00")

        entries_stmt = select(LedgerEntry).where(
            LedgerEntry.transaction_id == uuid.UUID(withdrawal_txn["id"])
        )
        entries_result = await db.execute(entries_stmt)
        entries = list(entries_result.scalars().all())
        assert len(entries) == 2
        assert_entries_are_balanced(entries)
        assert_entries_have_single_target(entries)

        debit = [e for e in entries if e.entry_type == LedgerEntryTypeEnum.DEBIT]
        credit = [e for e in entries if e.entry_type == LedgerEntryTypeEnum.CREDIT]
        assert len(debit) == 1
        assert len(credit) == 1
        assert debit[0].amount == credit[0].amount == Decimal("300.00")
        assert debit[0].customer_account_id == acct_a1.id
        assert debit[0].internal_account_id is None
        assert debit[0].balance_after == Decimal("3500.00")
        assert credit[0].internal_account_id == cash_account.id
        assert credit[0].customer_account_id is None
        assert credit[0].balance_after == usd_cash_baseline + Decimal("200.00")

    # --- 14. Withdrawal fails: insufficient funds ---
    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post("/api/v1/admin/transactions/withdrawal", json={
        "source_account_id": str(acct_b1.id),
        "amount": "999999.00",
    })
    assert resp.status_code == 400
    assert "Insufficient funds" in resp.json()["detail"]

    # --- 15. Customer can list own transactions ---
    client.cookies.clear()
    client.cookies.update(cust_a_cookie)
    resp = await client.get("/api/v1/customer/transactions")
    assert resp.status_code == 200
    txns = resp.json()
    # Customer A should see deposit, 2 transfers, and withdrawal = 4 transactions
    assert len(txns) >= 4

    # --- 16. Customer cannot see other user's transactions (404) ---
    # Get a transaction ID that only involves customer A's accounts
    cust_a_txn_id = txns[0]["id"]
    client.cookies.clear()
    client.cookies.update(cust_b_cookie)
    resp = await client.get(f"/api/v1/customer/transactions/{cust_a_txn_id}")
    # Customer B can see the A->B transfer but not A's self-transfers
    # Find a transaction that is purely between A's own accounts
    a_only_txn = next(
        (t for t in txns if t["source_account_id"] == str(acct_a1.id) and t["destination_account_id"] == str(acct_a2.id)),
        None
    )
    if a_only_txn:
        resp = await client.get(f"/api/v1/customer/transactions/{a_only_txn['id']}")
        assert resp.status_code == 404

    # --- 17. Staff with READ_TRANSACTIONS can list all ---
    client.cookies.clear()
    client.cookies.update(ae_cookie)
    resp = await client.get("/api/v1/admin/transactions")
    assert resp.status_code == 200
    assert len(resp.json()) >= 4

    # --- 18. Account Executive cannot deposit (no POST_BANK_TRANSACTIONS) ---
    resp = await client.post("/api/v1/admin/transactions/deposit", json={
        "destination_account_id": str(acct_a1.id),
        "amount": "100.00",
    })
    assert resp.status_code == 403

    # --- 19. Teller can deposit (has POST_BANK_TRANSACTIONS) ---
    client.cookies.clear()
    client.cookies.update(teller_cookie)
    resp = await client.post("/api/v1/admin/transactions/deposit", json={
        "destination_account_id": str(acct_b1.id),
        "amount": "50.00",
        "description": "Teller deposit",
    })
    assert resp.status_code == 201

    # acct_b1 = 700 + 50 = 750
    client.cookies.clear()
    client.cookies.update(cust_b_cookie)
    resp = await client.get(f"/api/v1/customer/accounts/{acct_b1.id}")
    assert Decimal(resp.json()["available_balance"]) == Decimal("750.00")

    # --- 20. Staff can read internal settlement accounts ---
    client.cookies.clear()
    client.cookies.update(teller_cookie)
    resp = await client.get("/api/v1/admin/internal-accounts")
    assert resp.status_code == 200
    internal_accounts = resp.json()
    cash_usd = next(
        account for account in internal_accounts if account["account_code"] == "CASH-USD"
    )
    cash_eur = next(
        account for account in internal_accounts if account["account_code"] == "CASH-EUR"
    )
    assert Decimal(cash_usd["balance"]) == usd_cash_baseline + Decimal("250.00")
    assert Decimal(cash_eur["balance"]) == eur_cash_baseline + Decimal("25.00")

    resp = await client.get(f"/api/v1/admin/internal-accounts/{cash_usd['id']}")
    assert resp.status_code == 200
    assert resp.json()["account_code"] == "CASH-USD"

    async with AsyncSession(engine, expire_on_commit=False) as db:
        cash_stmt = select(InternalAccount).where(
            InternalAccount.account_code == "CASH-USD"
        )
        cash_result = await db.execute(cash_stmt)
        cash_accounts = list(cash_result.scalars().all())
        assert len(cash_accounts) == 1
        assert cash_accounts[0].balance == usd_cash_baseline + Decimal("250.00")

    # --- 21. Customer cannot access admin transaction/internal-account endpoints ---
    client.cookies.clear()
    client.cookies.update(cust_a_cookie)
    resp = await client.get("/api/v1/admin/transactions")
    assert resp.status_code == 403
    resp = await client.get("/api/v1/admin/internal-accounts")
    assert resp.status_code == 403


async def test_ledger_entry_validation_helpers():
    base_entry = {
        "transaction_id": uuid.uuid4(),
        "entry_type": LedgerEntryTypeEnum.DEBIT,
        "amount": Decimal("10.00"),
        "currency": AccountCurrencyEnum.USD,
        "balance_after": Decimal("10.00"),
    }

    with pytest.raises(HTTPException) as missing_target:
        transaction_service._assert_single_ledger_target(LedgerEntry(**base_entry))
    assert missing_target.value.status_code == 500
    assert missing_target.value.detail == (
        "Ledger entry must reference exactly one account target"
    )

    with pytest.raises(HTTPException) as duplicate_target:
        transaction_service._assert_single_ledger_target(
            LedgerEntry(
                **base_entry,
                customer_account_id=uuid.uuid4(),
                internal_account_id=uuid.uuid4(),
            )
        )
    assert duplicate_target.value.status_code == 500
    assert duplicate_target.value.detail == (
        "Ledger entry must reference exactly one account target"
    )

    with pytest.raises(HTTPException) as unbalanced_entries:
        transaction_service._assert_ledger_entries_balanced(
            [
                LedgerEntry(
                    **base_entry,
                    customer_account_id=uuid.uuid4(),
                ),
                LedgerEntry(
                    transaction_id=uuid.uuid4(),
                    internal_account_id=uuid.uuid4(),
                    entry_type=LedgerEntryTypeEnum.CREDIT,
                    amount=Decimal("9.00"),
                    currency=AccountCurrencyEnum.USD,
                    balance_after=Decimal("9.00"),
                ),
            ]
        )
    assert unbalanced_entries.value.status_code == 500
    assert unbalanced_entries.value.detail == "Ledger entries are not balanced"
