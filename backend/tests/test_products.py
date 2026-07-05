import calendar
import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.accounts.enums import AccountCurrencyEnum, AccountTypeEnum
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
from modules.products.enums import ProductStatusEnum
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


def product_payload(
    code: str,
    *,
    account_type: AccountTypeEnum = AccountTypeEnum.SAVINGS,
    currency: AccountCurrencyEnum = AccountCurrencyEnum.USD,
    name: str = "Product",
) -> dict:
    return {
        "code": code,
        "name": name,
        "description": f"{name} description",
        "account_type": account_type.value,
        "currency": currency.value,
        "interest_rate": "1.20",
        "minimum_opening_deposit": "100.00",
        "minimum_balance": "25.00",
        "monthly_fee": "2.50",
    }


async def create_product(
    client: AsyncClient, cookie: dict[str, str], payload: dict
) -> dict:
    client.cookies.clear()
    client.cookies.update(cookie)
    resp = await client.post("/api/v1/admin/products", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def activate_product(
    client: AsyncClient, cookie: dict[str, str], product_id: str
) -> dict:
    client.cookies.clear()
    client.cookies.update(cookie)
    resp = await client.post(f"/api/v1/admin/products/{product_id}/activate")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def retire_product(
    client: AsyncClient, cookie: dict[str, str], product_id: str
) -> dict:
    client.cookies.clear()
    client.cookies.update(cookie)
    resp = await client.post(f"/api/v1/admin/products/{product_id}/retire")
    assert resp.status_code == 200, resp.text
    return resp.json()


def add_months(base_date: date, months: int) -> date:
    month_index = base_date.month - 1 + months
    year = base_date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(base_date.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


async def test_product_crud_filters_lifecycle_customer_browsing_and_rbac(
    client: AsyncClient,
):
    from infrastructure.database import engine

    unique = uuid.uuid4().hex[:8].upper()
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(
            db, f"prod_c_{unique}", RoleChoicesSchema.CUSTOMER
        )
        teller = await create_role_user(
            db, f"prod_t_{unique}", RoleChoicesSchema.TELLER
        )
        branch_manager = await create_role_user(
            db, f"prod_bm_{unique}", RoleChoicesSchema.BRANCH_MANAGER
        )
        admin = await create_role_user(
            db, f"prod_a_{unique}", RoleChoicesSchema.ADMIN
        )

    customer_cookie = await login_and_get_cookie(client, customer.email)
    teller_cookie = await login_and_get_cookie(client, teller.email)
    branch_manager_cookie = await login_and_get_cookie(client, branch_manager.email)
    admin_cookie = await login_and_get_cookie(client, admin.email)

    client.cookies.clear()
    client.cookies.update(customer_cookie)
    resp = await client.get("/api/v1/admin/products")
    assert resp.status_code == 403

    client.cookies.clear()
    client.cookies.update(teller_cookie)
    resp = await client.post(
        "/api/v1/admin/products",
        json=product_payload(f"TL{unique}", name="Teller Denied"),
    )
    assert resp.status_code == 403

    product = await create_product(
        client,
        admin_cookie,
        product_payload(f"SAV{unique}", name="Premium Savings"),
    )
    assert product["status"] == ProductStatusEnum.DRAFT.value
    assert product["code"] == f"SAV{unique}"

    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post(
        "/api/v1/admin/products",
        json=product_payload(f"SAV{unique}", name="Duplicate Savings"),
    )
    assert resp.status_code == 409

    client.cookies.clear()
    client.cookies.update(teller_cookie)
    resp = await client.get("/api/v1/admin/products")
    assert resp.status_code == 200
    assert any(item["id"] == product["id"] for item in resp.json())

    client.cookies.clear()
    client.cookies.update(customer_cookie)
    resp = await client.get("/api/v1/customer/products")
    assert resp.status_code == 200
    assert all(item["id"] != product["id"] for item in resp.json())

    active_product = await activate_product(client, admin_cookie, product["id"])
    assert active_product["status"] == ProductStatusEnum.ACTIVE.value

    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.get(
        "/api/v1/admin/products",
        params={
            "status": ProductStatusEnum.ACTIVE.value,
            "account_type": AccountTypeEnum.SAVINGS.value,
            "currency": AccountCurrencyEnum.USD.value,
        },
    )
    assert resp.status_code == 200
    filtered_ids = {item["id"] for item in resp.json()}
    assert product["id"] in filtered_ids

    client.cookies.clear()
    client.cookies.update(customer_cookie)
    resp = await client.get(
        "/api/v1/customer/products",
        params={
            "account_type": AccountTypeEnum.SAVINGS.value,
            "currency": AccountCurrencyEnum.USD.value,
        },
    )
    assert resp.status_code == 200
    customer_product_ids = {item["id"] for item in resp.json()}
    assert product["id"] in customer_product_ids

    client.cookies.clear()
    client.cookies.update(branch_manager_cookie)
    resp = await client.patch(
        f"/api/v1/admin/products/{product['id']}",
        json={
            "name": "Premium Savings Plus",
            "interest_rate": "1.80",
            "minimum_balance": "75.00",
            "monthly_fee": "1.75",
        },
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["name"] == "Premium Savings Plus"
    assert Decimal(updated["interest_rate"]) == Decimal("1.80")
    assert Decimal(updated["minimum_balance"]) == Decimal("75.00")
    assert Decimal(updated["monthly_fee"]) == Decimal("1.75")

    retired = await retire_product(client, branch_manager_cookie, product["id"])
    assert retired["status"] == ProductStatusEnum.RETIRED.value

    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post(f"/api/v1/admin/products/{product['id']}/activate")
    assert resp.status_code == 400
    assert "Retired products cannot be activated" in resp.json()["detail"]

    client.cookies.clear()
    client.cookies.update(customer_cookie)
    resp = await client.get("/api/v1/customer/products")
    assert resp.status_code == 200
    assert all(item["id"] != product["id"] for item in resp.json())


async def test_fixed_deposit_validation_and_immutable_terms(client: AsyncClient):
    from infrastructure.database import engine

    unique = uuid.uuid4().hex[:8].upper()
    async with AsyncSession(engine, expire_on_commit=False) as db:
        admin = await create_role_user(
            db, f"prod_fd_a_{unique}", RoleChoicesSchema.ADMIN
        )

    admin_cookie = await login_and_get_cookie(client, admin.email)

    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post(
        "/api/v1/admin/products",
        json=product_payload(
            f"FDX{unique}",
            account_type=AccountTypeEnum.FIXED_DEPOSIT,
            name="Missing Term Fixed Deposit",
        ),
    )
    assert resp.status_code == 422

    invalid_non_fixed = product_payload(
        f"SFX{unique}",
        account_type=AccountTypeEnum.SAVINGS,
        name="Savings With Fixed Terms",
    )
    invalid_non_fixed["fixed_deposit_term_months"] = 12
    invalid_non_fixed["early_withdrawal_penalty_rate"] = "1.50"
    resp = await client.post("/api/v1/admin/products", json=invalid_non_fixed)
    assert resp.status_code == 422

    fixed_payload = product_payload(
        f"FD{unique}",
        account_type=AccountTypeEnum.FIXED_DEPOSIT,
        name="Twelve Month Fixed Deposit",
    )
    fixed_payload["fixed_deposit_term_months"] = 12
    fixed_payload["early_withdrawal_penalty_rate"] = "1.50"
    product = await create_product(client, admin_cookie, fixed_payload)
    assert product["fixed_deposit_term_months"] == 12
    assert Decimal(product["early_withdrawal_penalty_rate"]) == Decimal("1.50")

    resp = await client.patch(
        f"/api/v1/admin/products/{product['id']}",
        json={
            "fixed_deposit_term_months": 24,
            "early_withdrawal_penalty_rate": "2.00",
        },
    )
    assert resp.status_code == 422

    resp = await client.get(f"/api/v1/admin/products/{product['id']}")
    assert resp.status_code == 200
    unchanged = resp.json()
    assert unchanged["fixed_deposit_term_months"] == 12
    assert Decimal(unchanged["early_withdrawal_penalty_rate"]) == Decimal("1.50")


async def test_account_opening_requires_active_product_and_snapshots_terms(
    client: AsyncClient,
):
    from infrastructure.database import engine

    unique = uuid.uuid4().hex[:8].upper()
    async with AsyncSession(engine, expire_on_commit=False) as db:
        customer = await create_role_user(
            db, f"prod_ac_{unique}", RoleChoicesSchema.CUSTOMER
        )
        admin = await create_role_user(
            db, f"prod_aa_{unique}", RoleChoicesSchema.ADMIN
        )
        await create_approved_profile(db, customer.id)

    admin_cookie = await login_and_get_cookie(client, admin.email)

    draft_product = await create_product(
        client,
        admin_cookie,
        product_payload(f"DR{unique}", name="Draft Product"),
    )

    retired_product = await create_product(
        client,
        admin_cookie,
        product_payload(f"RT{unique}", name="Retired Product"),
    )
    await retire_product(client, admin_cookie, retired_product["id"])

    fixed_payload = product_payload(
        f"FDO{unique}",
        account_type=AccountTypeEnum.FIXED_DEPOSIT,
        name="Openable Fixed Deposit",
    )
    fixed_payload["interest_rate"] = "4.25"
    fixed_payload["minimum_balance"] = "500.00"
    fixed_payload["monthly_fee"] = "0.00"
    fixed_payload["fixed_deposit_term_months"] = 12
    fixed_payload["early_withdrawal_penalty_rate"] = "1.50"
    fixed_product = await create_product(client, admin_cookie, fixed_payload)
    fixed_product = await activate_product(client, admin_cookie, fixed_product["id"])

    for product_id in (draft_product["id"], retired_product["id"]):
        client.cookies.clear()
        client.cookies.update(admin_cookie)
        resp = await client.post(
            "/api/v1/admin/accounts",
            json={
                "user_id": str(customer.id),
                "product_id": product_id,
                "account_name": "Rejected Product Account",
            },
        )
        assert resp.status_code == 400
        assert "Account product is not open" in resp.json()["detail"]

    resp = await client.post(
        "/api/v1/admin/accounts",
        json={
            "user_id": str(customer.id),
            "product_id": fixed_product["id"],
            "account_name": "Customer Fixed Deposit",
        },
    )
    assert resp.status_code == 201, resp.text
    account = resp.json()
    assert account["product_id"] == fixed_product["id"]
    assert account["account_type"] == AccountTypeEnum.FIXED_DEPOSIT.value
    assert account["currency"] == AccountCurrencyEnum.USD.value
    assert Decimal(account["interest_rate"]) == Decimal("4.25")
    assert Decimal(account["minimum_balance"]) == Decimal("500.00")
    assert Decimal(account["monthly_fee"]) == Decimal("0.00")
    assert account["fixed_deposit_term_months"] == 12
    assert Decimal(account["early_withdrawal_penalty_rate"]) == Decimal("1.50")

    opened_on = datetime.fromisoformat(account["opened_at"]).date()
    expected_maturity_date = add_months(opened_on, 12)
    assert date.fromisoformat(account["fixed_deposit_maturity_date"]) == (
        expected_maturity_date
    )
