import uuid
import pytest
from httpx import AsyncClient
from modules.auth.services import redis_client
from modules.users.schemas import SecurityQuestionsSchema

pytestmark = pytest.mark.asyncio


async def test_auth_happy_path_and_edge_cases(client: AsyncClient):
    # Unique values for this test run
    email = f"user_{uuid.uuid4().hex[:8]}@example.com"
    username = f"usr_{uuid.uuid4().hex[:8]}"
    id_no = uuid.uuid4().int % 100000000 + 1  # positive non-zero int

    register_payload = {
        "username": username,
        "email": email,
        "full_name": "John Doe",
        "id_no": id_no,
        "security_question": SecurityQuestionsSchema.FAVORITE_COLOR.value,
        "security_answer": "blue",
        "password": "strongpassword123",
        "confirm_password": "strongpassword123",
    }

    # --- EDGE CASE: Password Mismatch ---
    mismatch_payload = register_payload.copy()
    mismatch_payload["confirm_password"] = "differentpassword"
    resp = await client.post("/api/v1/auth/register", json=mismatch_payload)
    assert resp.status_code == 422
    assert "Passwords do not match" in resp.text

    # --- HAPPY PATH: Register ---
    resp = await client.post("/api/v1/auth/register", json=register_payload)
    assert resp.status_code == 200
    assert "registered successfully" in resp.json()["message"]

    # --- EDGE CASE: Duplicate Email Registration ---
    resp = await client.post("/api/v1/auth/register", json=register_payload)
    assert resp.status_code == 400
    assert "Email already registered" in resp.json()["detail"]

    # --- EDGE CASE: Login Pre-Verification (Should Fail) ---
    login_payload = {
        "email": email,
        "password": "strongpassword123",
    }
    resp = await client.post("/api/v1/auth/login", json=login_payload)
    assert resp.status_code == 400
    assert "pending verification" in resp.json()["detail"]

    # --- EDGE CASE: Invalid OTP verification ---
    verify_payload = {
        "email": email,
        "otp": "000000",
    }
    resp = await client.post("/api/v1/auth/verify-otp", json=verify_payload)
    assert resp.status_code == 400
    assert "Invalid or expired OTP" in resp.json()["detail"]

    # --- HAPPY PATH: OTP Retrieval & Verification ---
    otp_code = redis_client.get(f"otp:{email}")
    assert otp_code is not None

    verify_payload["otp"] = otp_code
    resp = await client.post("/api/v1/auth/verify-otp", json=verify_payload)
    assert resp.status_code == 200
    assert "verified successfully" in resp.json()["message"]

    # --- HAPPY PATH: Login (Returns HttpOnly Cookie) ---
    resp = await client.post("/api/v1/auth/login", json=login_payload)
    assert resp.status_code == 200
    assert "Login successful" in resp.json()["message"]
    assert "access_token" in resp.cookies
    
    # Store token cookie for subsequent request
    cookies = resp.cookies

    # --- HAPPY PATH: Access Protected Route ---
    resp = await client.get("/api/v1/users/me", cookies=cookies)
    assert resp.status_code == 200
    assert resp.json()["email"] == email
    assert resp.json()["full_name"] == "John Doe"

    # --- EDGE CASE: Querying Protected Route Without Cookies ---
    client.cookies.clear()
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 401
    assert "Access token missing" in resp.json()["detail"]

    # --- HAPPY PATH: Logout ---
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 200
    # access_token cookie should have expiration/max_age set to 0 or value cleared
    assert resp.cookies.get("access_token") in (None, "")


async def test_password_reset_flow(client: AsyncClient):
    # Unique values
    email = f"reset_{uuid.uuid4().hex[:8]}@example.com"
    username = f"usr_{uuid.uuid4().hex[:8]}"
    id_no = uuid.uuid4().int % 100000000 + 1

    register_payload = {
        "username": username,
        "email": email,
        "full_name": "Reset Tester",
        "id_no": id_no,
        "security_question": SecurityQuestionsSchema.BIRTH_CITY.value,
        "security_answer": "london",
        "password": "initialpassword123",
        "confirm_password": "initialpassword123",
    }

    # Register & Activate
    await client.post("/api/v1/auth/register", json=register_payload)
    otp_code = redis_client.get(f"otp:{email}")
    await client.post("/api/v1/auth/verify-otp", json={"email": email, "otp": otp_code})

    # --- HAPPY PATH: Forgot Password ---
    resp = await client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert resp.status_code == 200
    assert "password reset code has been sent" in resp.json()["message"]

    # Retrieve Reset OTP from Redis
    reset_otp = redis_client.get(f"otp:{email}")
    assert reset_otp is not None

    # Verify Reset OTP
    resp = await client.post("/api/v1/auth/verify-otp", json={"email": email, "otp": reset_otp})
    assert resp.status_code == 200
    assert "reset your password" in resp.json()["message"]

    # --- EDGE CASE: Reset Confirm Password Mismatch ---
    reset_payload = {
        "new_password": "newpassword999",
        "confirm_password": "mismatchedpassword",
    }
    resp = await client.post(f"/api/v1/auth/reset-password?email={email}", json=reset_payload)
    assert resp.status_code == 422
    assert "Passwords do not match" in resp.text

    # --- HAPPY PATH: Reset Password Confirm ---
    reset_payload["confirm_password"] = "newpassword999"
    resp = await client.post(f"/api/v1/auth/reset-password?email={email}", json=reset_payload)
    assert resp.status_code == 200
    assert "successful" in resp.json()["message"]

    # Verify Login works with the new password
    login_payload = {
        "email": email,
        "password": "newpassword999",
    }
    resp = await client.post("/api/v1/auth/login", json=login_payload)
    assert resp.status_code == 200
