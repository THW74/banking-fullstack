import uuid
import pytest
from datetime import date
from httpx import AsyncClient
from modules.auth.services import redis_client
from modules.users.schemas import SecurityQuestionsSchema
from modules.customer_profiles.enums import (
    EmploymentStatusEnum,
    GenderEnum,
    IdentificationTypeEnum,
    KycStatusEnum,
    MaritalStatusEnum,
    SalutationEnum,
)

pytestmark = pytest.mark.asyncio


async def register_and_login_user(client: AsyncClient, username: str, email: str, id_no: int) -> dict:
    # 1. Register
    register_payload = {
        "username": username,
        "email": email,
        "full_name": "Test User",
        "id_no": id_no,
        "security_question": SecurityQuestionsSchema.FAVORITE_COLOR.value,
        "security_answer": "blue",
        "password": "strongpassword123",
        "confirm_password": "strongpassword123",
    }
    resp = await client.post("/api/v1/auth/register", json=register_payload)
    assert resp.status_code == 200

    # 2. Get OTP and Verify
    otp_code = redis_client.get(f"otp:registration:{email}")
    assert otp_code is not None

    verify_payload = {
        "email": email,
        "otp": otp_code,
        "purpose": "registration",
    }
    resp = await client.post("/api/v1/auth/verify-otp", json=verify_payload)
    assert resp.status_code == 200

    # 3. Login
    login_payload = {
        "email": email,
        "password": "strongpassword123",
    }
    client.cookies.clear()
    resp = await client.post("/api/v1/auth/login", json=login_payload)
    assert resp.status_code == 200
    token = resp.cookies.get("access_token")
    client.cookies.clear()
    return {"access_token": token}


async def test_customer_profile_scenarios(client: AsyncClient):
    # Setup two users
    email_a = f"usera_{uuid.uuid4().hex[:8]}@example.com"
    username_a = f"ua_{uuid.uuid4().hex[:8]}"
    id_no_a = uuid.uuid4().int % 100000000 + 1

    email_b = f"userb_{uuid.uuid4().hex[:8]}@example.com"
    username_b = f"ub_{uuid.uuid4().hex[:8]}"
    id_no_b = uuid.uuid4().int % 100000000 + 1

    cookie_a = await register_and_login_user(client, username_a, email_a, id_no_a)
    cookie_b = await register_and_login_user(client, username_b, email_b, id_no_b)

    # --- 1. Customer B profile defaults to 404 ---
    client.cookies.clear()
    client.cookies.update(cookie_b)
    resp = await client.get("/api/v1/customer/profile")
    assert resp.status_code == 404

    # --- 2. Customer A creates draft profile ---
    client.cookies.clear()
    client.cookies.update(cookie_a)
    resp = await client.post("/api/v1/customer/profile", json={"phone_number": "+14155552671"})
    assert resp.status_code == 201
    assert resp.json()["kyc_status"] == KycStatusEnum.DRAFT.value
    assert resp.json()["phone_number"] == "tel:+1-415-555-2671"

    # --- 3. Duplicate profile creation returns 409 Conflict ---
    client.cookies.clear()
    client.cookies.update(cookie_a)
    resp = await client.post("/api/v1/customer/profile", json={"phone_number": "+14155552671"})
    assert resp.status_code == 409

    # --- 4. Isolation: Customer B gets their own profile (still 404, cannot see A's profile) ---
    client.cookies.clear()
    client.cookies.update(cookie_b)
    resp = await client.get("/api/v1/customer/profile")
    assert resp.status_code == 404

    # --- 5. Customer A updates draft with partial details ---
    client.cookies.clear()
    client.cookies.update(cookie_a)
    resp = await client.patch(
        "/api/v1/customer/profile",
        json={
            "title": "mr",
            "gender": "male",
            "date_of_birth": "1990-05-15",
            "country_of_birth": "US",
            "place_of_birth": "New York",
            "marital_status": "single",
            "nationality": "US",
        }
    )
    assert resp.status_code == 200
    assert resp.json()["place_of_birth"] == "New York"
    assert resp.json()["date_of_birth"] == "1990-05-15"

    # --- 6. Custom Pydantic Validations ---
    # Age under 18 check
    client.cookies.clear()
    client.cookies.update(cookie_a)
    resp = await client.patch("/api/v1/customer/profile", json={"date_of_birth": str(date.today())})
    assert resp.status_code == 422
    assert "must be at least 18 years old" in resp.text

    # Negative annual income check
    client.cookies.clear()
    client.cookies.update(cookie_a)
    resp = await client.patch("/api/v1/customer/profile", json={"annual_income": -500})
    assert resp.status_code == 422
    assert "must be non-negative" in resp.text

    # Future employment date check
    client.cookies.clear()
    client.cookies.update(cookie_a)
    resp = await client.patch("/api/v1/customer/profile", json={"date_of_employment": "2050-01-01"})
    assert resp.status_code == 422
    assert "cannot be in the future" in resp.text

    # Reset DOB back to valid
    resp = await client.patch("/api/v1/customer/profile", json={"date_of_birth": "1990-05-15"})
    assert resp.status_code == 200

    # --- 7. Incomplete submission fails with 400 ---
    client.cookies.clear()
    client.cookies.update(cookie_a)
    resp = await client.post("/api/v1/customer/profile/submit")
    assert resp.status_code == 400
    assert "Incomplete KYC data" in resp.json()["detail"]

    # --- 8. Provide complete required fields & submit successfully ---
    client.cookies.clear()
    client.cookies.update(cookie_a)
    # Fill remaining fields
    resp = await client.patch(
        "/api/v1/customer/profile",
        json={
            "identification_type": IdentificationTypeEnum.PASSPORT.value,
            "identification_number": "P1234567",
            "id_issue_date": "2020-01-01",
            "id_expiry_date": "2030-01-01",
            "address": "123 Main St",
            "city": "New York",
            "country": "US",
            "employment_status": EmploymentStatusEnum.UNEMPLOYED.value,
            "id_photo_url": "http://example.com/id.jpg",
        }
    )
    assert resp.status_code == 200

    # Submit
    resp = await client.post("/api/v1/customer/profile/submit")
    assert resp.status_code == 200
    assert resp.json()["kyc_status"] == KycStatusEnum.SUBMITTED.value
    assert resp.json()["submitted_at"] is not None

    # --- 9. Locked state: submitted profile cannot be updated ---
    client.cookies.clear()
    client.cookies.update(cookie_a)
    resp = await client.patch("/api/v1/customer/profile", json={"city": "Boston"})
    assert resp.status_code == 400
    assert "Only draft or rejected profiles can be updated" in resp.json()["detail"]

    resp = await client.post("/api/v1/customer/profile/submit")
    assert resp.status_code == 400
    assert "Only draft or rejected profiles can be submitted" in resp.json()["detail"]


async def test_kyc_conditional_employment_rules(client: AsyncClient):
    email = f"userc_{uuid.uuid4().hex[:8]}@example.com"
    username = f"uc_{uuid.uuid4().hex[:8]}"
    id_no = uuid.uuid4().int % 100000000 + 1

    cookie = await register_and_login_user(client, username, email, id_no)

    client.cookies.clear()
    client.cookies.update(cookie)
    # Create draft
    resp = await client.post("/api/v1/customer/profile", json={"phone_number": "+14155552671"})
    assert resp.status_code == 201

    # Fill all fields EXCEPT employment, but set employment_status to EMPLOYED
    resp = await client.patch(
        "/api/v1/customer/profile",
        json={
            "title": "mr",
            "gender": "male",
            "date_of_birth": "1990-05-15",
            "country_of_birth": "US",
            "place_of_birth": "New York",
            "marital_status": "single",
            "nationality": "US",
            "identification_type": IdentificationTypeEnum.PASSPORT.value,
            "identification_number": "P1234567",
            "id_issue_date": "2020-01-01",
            "id_expiry_date": "2030-01-01",
            "address": "123 Main St",
            "city": "New York",
            "country": "US",
            "employment_status": EmploymentStatusEnum.EMPLOYED.value,
            "id_photo_url": "http://example.com/id.jpg",
        }
    )
    assert resp.status_code == 200

    # Submission should fail because employer fields are missing for an EMPLOYED user
    resp = await client.post("/api/v1/customer/profile/submit")
    assert resp.status_code == 400
    assert "employer_name is required" in resp.json()["detail"]

    # Fill employer fields
    resp = await client.patch(
        "/api/v1/customer/profile",
        json={
            "employer_name": "Acme Corp",
            "employer_address": "456 Corporate Blvd",
            "employer_city": "New York",
            "employer_country": "US",
            "annual_income": 85000.0,
            "date_of_employment": "2022-01-01",
        }
    )
    assert resp.status_code == 200

    # Submission should now succeed
    resp = await client.post("/api/v1/customer/profile/submit")
    assert resp.status_code == 200
    assert resp.json()["kyc_status"] == KycStatusEnum.SUBMITTED.value


async def test_kyc_rejected_profile_can_be_edited_and_resubmitted(client: AsyncClient):
    email = f"userd_{uuid.uuid4().hex[:8]}@example.com"
    username = f"ud_{uuid.uuid4().hex[:8]}"
    id_no = uuid.uuid4().int % 100000000 + 1

    cookie = await register_and_login_user(client, username, email, id_no)

    # Let's directly write to DB to set status to REJECTED for this test scenario
    from infrastructure.database import engine
    from sqlmodel import select
    from sqlalchemy.ext.asyncio import AsyncSession
    from modules.users.models import User
    from modules.customer_profiles.models import CustomerProfile

    async with AsyncSession(engine) as db:
        user_res = await db.execute(select(User).where(User.email == email))
        user = user_res.scalar_one()

        db_profile = CustomerProfile(
            user_id=user.id,
            title=SalutationEnum.MR,
            gender=GenderEnum.MALE,
            date_of_birth=date(1990, 5, 15),
            country_of_birth="US",
            place_of_birth="New York",
            marital_status=MaritalStatusEnum.SINGLE,
            nationality="US",
            identification_type=IdentificationTypeEnum.PASSPORT,
            identification_number="P1234567",
            id_issue_date=date(2020, 1, 1),
            id_expiry_date=date(2030, 1, 1),
            phone_number="tel:+1-415-555-2671",
            address="123 Main St",
            city="New York",
            country="US",
            employment_status=EmploymentStatusEnum.UNEMPLOYED,
            id_photo_url="http://example.com/id.jpg",
            kyc_status=KycStatusEnum.REJECTED,
            rejection_reason="Incorrect ID photo",
        )
        db.add(db_profile)
        await db.commit()

    # Now edit rejected profile
    client.cookies.clear()
    client.cookies.update(cookie)
    resp = await client.patch("/api/v1/customer/profile", json={"id_photo_url": "http://example.com/correct_id.jpg"})
    assert resp.status_code == 200
    assert resp.json()["id_photo_url"] == "http://example.com/correct_id.jpg"
    assert resp.json()["kyc_status"] == KycStatusEnum.REJECTED.value

    # Resubmit
    resp = await client.post("/api/v1/customer/profile/submit")
    assert resp.status_code == 200
    assert resp.json()["kyc_status"] == KycStatusEnum.SUBMITTED.value
    assert resp.json()["rejection_reason"] is None
