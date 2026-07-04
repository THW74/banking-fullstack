import uuid
import pytest
from datetime import date
from httpx import AsyncClient
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.users.models import User
from modules.users.schemas import RoleChoicesSchema, AccountStatusSchema, SecurityQuestionsSchema
from modules.customer_profiles.enums import KycStatusEnum, EmploymentStatusEnum
from modules.customer_profiles.models import CustomerProfile
from modules.auth.services import auth_service
from infrastructure.database import get_session

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


async def create_and_submit_profile(client: AsyncClient, cookie: dict) -> uuid.UUID:
    # 1. Create draft
    client.cookies.clear()
    client.cookies.update(cookie)
    resp = await client.post(
        "/api/v1/customer/profile",
        json={"phone_number": "+14155552671"}
    )
    assert resp.status_code == 201
    profile_id = uuid.UUID(resp.json()["id"])

    # 2. Update draft with completeness info
    resp = await client.patch(
        "/api/v1/customer/profile",
        json={
            "title": "mr",
            "gender": "male",
            "date_of_birth": "1990-01-01",
            "country_of_birth": "US",
            "place_of_birth": "San Francisco",
            "marital_status": "single",
            "nationality": "US",
            "identification_type": "passport",
            "identification_number": "P1234567",
            "id_issue_date": "2020-01-01",
            "id_expiry_date": "2030-01-01",
            "address": "123 Market St",
            "city": "San Francisco",
            "country": "US",
            "employment_status": "employed",
            "employer_name": "Tech Corp",
            "employer_address": "456 Mission St",
            "employer_city": "San Francisco",
            "employer_country": "US",
            "annual_income": 120000,
            "date_of_employment": "2021-01-01",
            "id_photo_url": "https://example.com/passport.jpg",
        }
    )
    assert resp.status_code == 200

    # 3. Submit profile
    resp = await client.post("/api/v1/customer/profile/submit")
    assert resp.status_code == 200
    assert resp.json()["kyc_status"] == KycStatusEnum.SUBMITTED.value
    return profile_id


async def test_unauthenticated_requests(client: AsyncClient):
    client.cookies.clear()
    resp = await client.get("/api/v1/admin/kyc/profiles")
    assert resp.status_code == 401

    resp = await client.post(f"/api/v1/admin/kyc/profiles/{uuid.uuid4()}/approve")
    assert resp.status_code == 401


async def test_role_based_access_controls(client: AsyncClient):
    # Setup users
    from infrastructure.database import engine
    async with AsyncSession(engine, expire_on_commit=False) as db:
        cust = await create_role_user(db, f"c_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.CUSTOMER)
        tell = await create_role_user(db, f"t_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.TELLER)
        ae = await create_role_user(db, f"ae_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.ACCOUNT_EXECUTIVE)
        bm = await create_role_user(db, f"bm_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.BRANCH_MANAGER)

    cust_cookie = await login_and_get_cookie(client, cust.email)
    tell_cookie = await login_and_get_cookie(client, tell.email)
    ae_cookie = await login_and_get_cookie(client, ae.email)
    bm_cookie = await login_and_get_cookie(client, bm.email)

    # 1. Customer submits a profile
    profile_id = await create_and_submit_profile(client, cust_cookie)

    # 2. Customer is blocked from admin routes (403)
    client.cookies.clear()
    client.cookies.update(cust_cookie)
    resp = await client.get("/api/v1/admin/kyc/profiles")
    assert resp.status_code == 403
    resp = await client.get(f"/api/v1/admin/kyc/profiles/{profile_id}")
    assert resp.status_code == 403
    resp = await client.post(f"/api/v1/admin/kyc/profiles/{profile_id}/start-review")
    assert resp.status_code == 403
    resp = await client.post(f"/api/v1/admin/kyc/profiles/{profile_id}/approve")
    assert resp.status_code == 403
    resp = await client.post(f"/api/v1/admin/kyc/profiles/{profile_id}/reject", json={"rejection_reason": "No photo"})
    assert resp.status_code == 403

    # 3. Teller is blocked from all admin routes (403)
    client.cookies.clear()
    client.cookies.update(tell_cookie)
    resp = await client.get("/api/v1/admin/kyc/profiles")
    assert resp.status_code == 403
    resp = await client.post(f"/api/v1/admin/kyc/profiles/{profile_id}/approve")
    assert resp.status_code == 403

    # 4. Account Executive (AE) can read/list but not start-review, approve, or reject
    client.cookies.clear()
    client.cookies.update(ae_cookie)
    resp = await client.get("/api/v1/admin/kyc/profiles")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    resp = await client.get(f"/api/v1/admin/kyc/profiles/{profile_id}")
    assert resp.status_code == 200

    resp = await client.post(f"/api/v1/admin/kyc/profiles/{profile_id}/start-review")
    assert resp.status_code == 403

    resp = await client.post(f"/api/v1/admin/kyc/profiles/{profile_id}/approve")
    assert resp.status_code == 403

    resp = await client.post(f"/api/v1/admin/kyc/profiles/{profile_id}/reject", json={"rejection_reason": "Invalid"})
    assert resp.status_code == 403

    # 5. Branch Manager (BM) can start-review, approve, and reject
    client.cookies.clear()
    client.cookies.update(bm_cookie)
    
    # Get detail before review
    resp = await client.get(f"/api/v1/admin/kyc/profiles/{profile_id}")
    assert resp.status_code == 200
    assert resp.json()["reviewed_by_user_id"] is None

    # Start review
    resp = await client.post(f"/api/v1/admin/kyc/profiles/{profile_id}/start-review")
    assert resp.status_code == 200
    assert resp.json()["kyc_status"] == KycStatusEnum.UNDER_REVIEW.value
    assert resp.json()["reviewed_by_user_id"] == str(bm.id)

    # Approve
    resp = await client.post(f"/api/v1/admin/kyc/profiles/{profile_id}/approve")
    assert resp.status_code == 200
    assert resp.json()["kyc_status"] == KycStatusEnum.APPROVED.value
    assert resp.json()["reviewed_by_user_id"] == str(bm.id)
    assert resp.json()["reviewed_at"] is not None


async def test_rejection_and_resubmission(client: AsyncClient):
    from infrastructure.database import engine
    async with AsyncSession(engine, expire_on_commit=False) as db:
        cust = await create_role_user(db, f"cr_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.CUSTOMER)
        admin = await create_role_user(db, f"ad_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.ADMIN)

    cust_cookie = await login_and_get_cookie(client, cust.email)
    admin_cookie = await login_and_get_cookie(client, admin.email)

    profile_id = await create_and_submit_profile(client, cust_cookie)

    # 1. Admin rejects profile (missing reason => 422 validation, empty reason => 400)
    client.cookies.clear()
    client.cookies.update(admin_cookie)
    
    # Missing field
    resp = await client.post(f"/api/v1/admin/kyc/profiles/{profile_id}/reject", json={})
    assert resp.status_code == 422

    # Empty string
    resp = await client.post(f"/api/v1/admin/kyc/profiles/{profile_id}/reject", json={"rejection_reason": ""})
    assert resp.status_code == 422  # validation fails on min_length=1

    # Valid rejection
    resp = await client.post(f"/api/v1/admin/kyc/profiles/{profile_id}/reject", json={"rejection_reason": "Blurry document photo"})
    assert resp.status_code == 200
    assert resp.json()["kyc_status"] == KycStatusEnum.REJECTED.value
    assert resp.json()["rejection_reason"] == "Blurry document photo"
    assert resp.json()["reviewed_by_user_id"] == str(admin.id)

    # 2. Customer updates and resubmits
    client.cookies.clear()
    client.cookies.update(cust_cookie)
    
    # Check that customer response schema does not leak reviewed_by_user_id
    resp = await client.get("/api/v1/customer/profile")
    assert resp.status_code == 200
    assert "reviewed_by_user_id" not in resp.json()

    # Update photo
    resp = await client.patch("/api/v1/customer/profile", json={"id_photo_url": "https://example.com/clear.jpg"})
    assert resp.status_code == 200
    assert resp.json()["id_photo_url"] == "https://example.com/clear.jpg"
    assert resp.json()["kyc_status"] == KycStatusEnum.REJECTED.value  # remains rejected until submit

    # Resubmit
    resp = await client.post("/api/v1/customer/profile/submit")
    assert resp.status_code == 200
    assert resp.json()["kyc_status"] == KycStatusEnum.SUBMITTED.value
    assert resp.json()["rejection_reason"] is None


async def test_state_locks_and_transitions(client: AsyncClient):
    from infrastructure.database import engine
    async with AsyncSession(engine, expire_on_commit=False) as db:
        cust = await create_role_user(db, f"cl_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.CUSTOMER)
        admin = await create_role_user(db, f"al_{uuid.uuid4().hex[:6]}", RoleChoicesSchema.ADMIN)

    cust_cookie = await login_and_get_cookie(client, cust.email)
    admin_cookie = await login_and_get_cookie(client, admin.email)

    # 1. Cannot approve/reject a DRAFT profile
    client.cookies.clear()
    client.cookies.update(cust_cookie)
    # Create draft but don't submit
    resp = await client.post(
        "/api/v1/customer/profile",
        json={"phone_number": "+14155552671"}
    )
    assert resp.status_code == 201
    profile_id = uuid.UUID(resp.json()["id"])

    # Admin attempts approve/reject draft
    client.cookies.clear()
    client.cookies.update(admin_cookie)
    resp = await client.post(f"/api/v1/admin/kyc/profiles/{profile_id}/approve")
    assert resp.status_code == 400
    assert "submitted or under review" in resp.json()["detail"]

    # 2. Transition draft to SUBMITTED
    client.cookies.clear()
    client.cookies.update(cust_cookie)
    # Fill in completeness requirements
    resp = await client.patch(
        "/api/v1/customer/profile",
        json={
            "title": "mr",
            "gender": "male",
            "date_of_birth": "1990-01-01",
            "country_of_birth": "US",
            "place_of_birth": "San Francisco",
            "marital_status": "single",
            "nationality": "US",
            "identification_type": "passport",
            "identification_number": "P1234567",
            "id_issue_date": "2020-01-01",
            "id_expiry_date": "2030-01-01",
            "address": "123 Market St",
            "city": "San Francisco",
            "country": "US",
            "employment_status": "employed",
            "employer_name": "Tech Corp",
            "employer_address": "456 Mission St",
            "employer_city": "San Francisco",
            "employer_country": "US",
            "annual_income": 120000,
            "date_of_employment": "2021-01-01",
            "id_photo_url": "https://example.com/passport.jpg",
        }
    )
    assert resp.status_code == 200
    resp = await client.post("/api/v1/customer/profile/submit")
    assert resp.status_code == 200

    # 3. Double-review transition locks
    client.cookies.clear()
    client.cookies.update(admin_cookie)
    
    # Approve
    resp = await client.post(f"/api/v1/admin/kyc/profiles/{profile_id}/approve")
    assert resp.status_code == 200
    assert resp.json()["kyc_status"] == KycStatusEnum.APPROVED.value

    # Approve again => 400 Bad Request
    resp = await client.post(f"/api/v1/admin/kyc/profiles/{profile_id}/approve")
    assert resp.status_code == 400

    # Reject approved profile => 400 Bad Request
    resp = await client.post(f"/api/v1/admin/kyc/profiles/{profile_id}/reject", json={"rejection_reason": "No longer needed"})
    assert resp.status_code == 400
