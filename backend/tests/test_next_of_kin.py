import uuid
import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from modules.users.models import User
from modules.users.schemas import RoleChoicesSchema, AccountStatusSchema, SecurityQuestionsSchema
from modules.next_of_kin.enums import RelationshipTypeEnum
from modules.next_of_kin.models import NextOfKin
from modules.auth.services import auth_service

pytestmark = pytest.mark.asyncio


# Helper function to create users
async def register_and_login_user(client: AsyncClient, username: str, email: str, id_no: int) -> dict:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": email,
            "full_name": "Test User",
            "id_no": id_no,
            "password": "Password123!",
            "confirm_password": "Password123!",
            "security_question": SecurityQuestionsSchema.FAVORITE_COLOR.value,
            "security_answer": "blue",
        }
    )
    assert resp.status_code == 200, f"Register failed: {resp.text}"

    # Retrieve valid OTP from Redis and verify
    from modules.auth.services import redis_client
    otp_code = redis_client.get(f"otp:registration:{email}")
    assert otp_code is not None

    verify_resp = await client.post(
        "/api/v1/auth/verify-otp",
        json={
            "email": email,
            "otp": otp_code,
            "purpose": "registration",
        }
    )
    assert verify_resp.status_code == 200, f"Verify failed: {verify_resp.text}"

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Password123!"}
    )
    assert resp.status_code == 200
    token = resp.cookies.get("access_token")
    return {"access_token": token}


async def test_next_of_kin_scenarios(client: AsyncClient):
    # Setup two users
    email_a = f"usera_{uuid.uuid4().hex[:8]}@example.com"
    username_a = f"ua_{uuid.uuid4().hex[:8]}"
    id_no_a = uuid.uuid4().int % 100000000 + 1

    email_b = f"userb_{uuid.uuid4().hex[:8]}@example.com"
    username_b = f"ub_{uuid.uuid4().hex[:8]}"
    id_no_b = uuid.uuid4().int % 100000000 + 1

    cookie_a = await register_and_login_user(client, username_a, email_a, id_no_a)
    cookie_b = await register_and_login_user(client, username_b, email_b, id_no_b)

    # --- 1. Customer B lists is empty ---
    client.cookies.clear()
    client.cookies.update(cookie_b)
    resp = await client.get("/api/v1/customer/next-of-kin")
    assert resp.status_code == 200
    assert resp.json() == []

    # --- 2. Customer A creates a next of kin contact ---
    client.cookies.clear()
    client.cookies.update(cookie_a)
    payload_1 = {
        "full_name": "Jane Doe",
        "relationship": RelationshipTypeEnum.SPOUSE.value,
        "email": "jane@example.com",
        "phone_number": "+14155552671",
        "address": "123 Market St",
        "city": "San Francisco",
        "country": "US",
        "nationality": "US",
        "id_number": "ID12345",
        "is_primary": True,
    }
    resp = await client.post("/api/v1/customer/next-of-kin", json=payload_1)
    assert resp.status_code == 201, f"Code: {resp.status_code}, Body: {resp.text}"
    kin_1_id = resp.json()["id"]
    assert resp.json()["full_name"] == "Jane Doe"
    assert resp.json()["is_primary"] is True
    assert resp.json()["created_at"] is not None

    # --- 3. Customer A creates a second next of kin (not primary) ---
    payload_2 = {
        "full_name": "John Doe",
        "relationship": RelationshipTypeEnum.PARENT.value,
        "phone_number": "+14155552672",
        "address": "456 Mission St",
        "city": "San Francisco",
        "country": "US",
        "is_primary": False,
    }
    resp = await client.post("/api/v1/customer/next-of-kin", json=payload_2)
    assert resp.status_code == 201
    kin_2_id = resp.json()["id"]
    assert resp.json()["is_primary"] is False

    # Check listing lists both
    resp = await client.get("/api/v1/customer/next-of-kin")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    # --- 4. User isolation checks ---
    client.cookies.clear()
    client.cookies.update(cookie_b)
    resp = await client.get(f"/api/v1/customer/next-of-kin/{kin_1_id}")
    assert resp.status_code == 404

    resp = await client.patch(f"/api/v1/customer/next-of-kin/{kin_1_id}", json={"full_name": "Hack"})
    assert resp.status_code == 404

    resp = await client.delete(f"/api/v1/customer/next-of-kin/{kin_1_id}")
    assert resp.status_code == 404

    resp = await client.post(f"/api/v1/customer/next-of-kin/{kin_1_id}/primary")
    assert resp.status_code == 404

    # --- 5. Atomic primary flag handling ---
    client.cookies.clear()
    client.cookies.update(cookie_a)

    resp = await client.post(f"/api/v1/customer/next-of-kin/{kin_2_id}/primary")
    assert resp.status_code == 200
    assert resp.json()["is_primary"] is True

    resp = await client.get(f"/api/v1/customer/next-of-kin/{kin_1_id}")
    assert resp.status_code == 200
    assert resp.json()["is_primary"] is False

    # --- 6. Creation / Update primary resets ---
    resp = await client.patch(f"/api/v1/customer/next-of-kin/{kin_1_id}", json={"is_primary": True})
    assert resp.status_code == 200
    assert resp.json()["is_primary"] is True

    resp = await client.get(f"/api/v1/customer/next-of-kin/{kin_2_id}")
    assert resp.json()["is_primary"] is False

    payload_3 = {
        "full_name": "Baby Doe",
        "relationship": RelationshipTypeEnum.CHILD.value,
        "phone_number": "+14155552673",
        "address": "789 Broadway",
        "city": "San Francisco",
        "country": "US",
        "is_primary": True,
    }
    resp = await client.post("/api/v1/customer/next-of-kin", json=payload_3)
    assert resp.status_code == 201
    kin_3_id = resp.json()["id"]

    resp = await client.get(f"/api/v1/customer/next-of-kin/{kin_1_id}")
    assert resp.json()["is_primary"] is False

    # --- 7. Regression test for deleting a primary contact ---
    resp = await client.delete(f"/api/v1/customer/next-of-kin/{kin_3_id}")
    assert resp.status_code == 204

    resp = await client.get(f"/api/v1/customer/next-of-kin/{kin_1_id}")
    assert resp.json()["is_primary"] is False
    resp = await client.get(f"/api/v1/customer/next-of-kin/{kin_2_id}")
    assert resp.json()["is_primary"] is False

    # --- 8. Validation edge cases ---
    resp = await client.post(
        "/api/v1/customer/next-of-kin",
        json={
            "full_name": "Test Validation",
            "relationship": RelationshipTypeEnum.OTHER.value,
            "phone_number": "12345",
            "address": "Street",
            "city": "City",
            "country": "US",
        }
    )
    assert resp.status_code == 422

    resp = await client.post(
        "/api/v1/customer/next-of-kin",
        json={
            "full_name": "Test Validation",
            "relationship": RelationshipTypeEnum.OTHER.value,
            "phone_number": "+14155552671",
            "address": "Street",
            "city": "City",
            "country": "USA",
        }
    )
    assert resp.status_code == 422

    # --- 9. Unauthenticated requests return 401 ---
    client.cookies.clear()
    resp = await client.get("/api/v1/customer/next-of-kin")
    assert resp.status_code == 401
