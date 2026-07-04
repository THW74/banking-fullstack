import uuid
import pytest
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
from modules.accounts.models import BankAccount
from modules.auth.services import auth_service

pytestmark = pytest.mark.asyncio


# Helper function to create users with specific roles
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


from datetime import date, timezone

async def create_and_approve_kyc(client: AsyncClient, db: AsyncSession, user_id: uuid.UUID, bm_cookie: dict) -> None:
    # Directly insert approved CustomerProfile into DB to keep tests fast
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


async def test_accounts_scenarios(client: AsyncClient):
    # Setup roles
    from infrastructure.database import engine
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer_a = await create_role_user(db, f"ca_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.CUSTOMER)
        customer_b = await create_role_user(db, f"cb_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.CUSTOMER)
        teller = await create_role_user(db, f"tl_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.TELLER)
        ae = await create_role_user(db, f"ae_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.ACCOUNT_EXECUTIVE)
        bm = await create_role_user(db, f"bm_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.BRANCH_MANAGER)
        admin = await create_role_user(db, f"ad_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.ADMIN)

    customer_a_cookie = await login_and_get_cookie(client, customer_a.email)
    customer_b_cookie = await login_and_get_cookie(client, customer_b.email)
    teller_cookie = await login_and_get_cookie(client, teller.email)
    ae_cookie = await login_and_get_cookie(client, ae.email)
    bm_cookie = await login_and_get_cookie(client, bm.email)
    admin_cookie = await login_and_get_cookie(client, admin.email)

    # --- 1. Attempt to create bank account for Customer A before KYC approved (fails 400) ---
    client.cookies.clear()
    client.cookies.update(admin_cookie)
    payload_a1 = {
        "user_id": str(customer_a.id),
        "account_type": AccountTypeEnum.SAVINGS.value,
        "currency": AccountCurrencyEnum.USD.value,
        "account_name": "Customer A Savings",
        "is_primary": True,
    }
    resp = await client.post("/api/v1/admin/accounts", json=payload_a1)
    assert resp.status_code == 400
    assert "Only approved KYC customers" in resp.text

    # --- 2. Approve KYC for Customer A and create account (succeeds 201) ---
    async with AsyncSession(engine, expire_on_commit=False) as db:
        await create_and_approve_kyc(client, db, customer_a.id, bm_cookie)

    resp = await client.post("/api/v1/admin/accounts", json=payload_a1)
    assert resp.status_code == 201, f"Create failed: {resp.text}"
    acc_a1 = resp.json()
    assert acc_a1["account_name"] == "Customer A Savings"
    assert acc_a1["account_status"] == AccountStatusEnum.ACTIVE.value
    assert acc_a1["is_primary"] is True
    assert len(acc_a1["account_number"]) == 10

    # --- 3. Create a second account (checking) for Customer A, setting as primary ---
    payload_a2 = {
        "user_id": str(customer_a.id),
        "account_type": AccountTypeEnum.CHECKING.value,
        "currency": AccountCurrencyEnum.USD.value,
        "account_name": "Customer A Checking",
        "is_primary": True,
    }
    resp = await client.post("/api/v1/admin/accounts", json=payload_a2)
    assert resp.status_code == 201
    acc_a2 = resp.json()
    assert acc_a2["is_primary"] is True

    # Verify that first account has been reset to is_primary = False (atomic check)
    client.cookies.clear()
    client.cookies.update(customer_a_cookie)
    resp = await client.get(f"/api/v1/customer/accounts/{acc_a1['id']}")
    assert resp.status_code == 200
    assert resp.json()["is_primary"] is False

    # --- 4. User isolation checks (Customer B cannot view Customer A's accounts) ---
    client.cookies.clear()
    client.cookies.update(customer_b_cookie)
    resp = await client.get(f"/api/v1/customer/accounts/{acc_a1['id']}")
    assert resp.status_code == 404

    resp = await client.get("/api/v1/customer/accounts")
    assert resp.status_code == 200
    assert len(resp.json()) == 0

    # --- 5. Tellers and Account Executives cannot open bank accounts (returns 403) ---
    client.cookies.clear()
    client.cookies.update(teller_cookie)
    resp = await client.post("/api/v1/admin/accounts", json=payload_a2)
    assert resp.status_code == 403

    client.cookies.clear()
    client.cookies.update(ae_cookie)
    resp = await client.post("/api/v1/admin/accounts", json=payload_a2)
    assert resp.status_code == 403

    # --- 6. Admin, Branch Manager, Account Executive, and Teller can list/read all accounts ---
    for cookie in [teller_cookie, ae_cookie, bm_cookie, admin_cookie]:
        client.cookies.clear()
        client.cookies.update(cookie)
        resp = await client.get("/api/v1/admin/accounts")
        assert resp.status_code == 200
        assert len(resp.json()) >= 2
        resp = await client.get(f"/api/v1/admin/accounts/{acc_a1['id']}")
        assert resp.status_code == 200

    # --- 7. Admin/Manager can freeze an account ---
    client.cookies.clear()
    client.cookies.update(bm_cookie)
    resp = await client.post(f"/api/v1/admin/accounts/{acc_a1['id']}/freeze")
    assert resp.status_code == 200
    assert resp.json()["account_status"] == AccountStatusEnum.FROZEN.value

    # Check that frozen accounts are still retrievable
    resp = await client.get(f"/api/v1/admin/accounts/{acc_a1['id']}")
    assert resp.status_code == 200

    # --- 8. Admin/Manager can close an account ---
    resp = await client.post(f"/api/v1/admin/accounts/{acc_a1['id']}/close")
    assert resp.status_code == 200
    assert resp.json()["account_status"] == AccountStatusEnum.CLOSED.value
    assert resp.json()["closed_at"] is not None

    # --- 9. Closed accounts cannot be frozen or closed again (400) ---
    resp = await client.post(f"/api/v1/admin/accounts/{acc_a1['id']}/freeze")
    assert resp.status_code == 400
    assert "Cannot freeze a closed account" in resp.text

    resp = await client.post(f"/api/v1/admin/accounts/{acc_a1['id']}/close")
    assert resp.status_code == 400
    assert "Account is already closed" in resp.text

    # --- 10. Unauthenticated requests return 401 ---
    client.cookies.clear()
    resp = await client.get("/api/v1/customer/accounts")
    assert resp.status_code == 401

    resp = await client.get("/api/v1/admin/accounts")
    assert resp.status_code == 401
