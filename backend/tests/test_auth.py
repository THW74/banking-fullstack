import uuid
import pytest
from httpx import AsyncClient
from modules.auth.services import redis_client
from modules.users.schemas import SecurityQuestionsSchema
from infrastructure.config import Settings

pytestmark = pytest.mark.asyncio


async def test_rejects_placeholder_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "secret-key-placeholder-change-in-production")
    with pytest.raises(ValueError) as exc:
        Settings()
    assert "JWT_SECRET_KEY is insecure or missing" in str(exc.value)


async def test_auth_happy_path_and_edge_cases(client: AsyncClient):
    # Unique values for this test run
    email = f"user_{uuid.uuid4().hex[:8]}@example.com"
    username = f"usr_{uuid.uuid4().hex[:8]}"
    id_no = uuid.uuid4().int % 100000000 + 1

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

    # --- EDGE CASE: Invalid OTP verification & lockout after 5 failures ---
    verify_payload = {
        "email": email,
        "otp": "000000",
        "purpose": "registration",
    }
    
    # 5 failed verification attempts
    for _ in range(5):
        resp = await client.post("/api/v1/auth/verify-otp", json=verify_payload)
        assert resp.status_code == 400
        assert "Invalid or expired OTP" in resp.json()["detail"]

    # 6th attempt should trigger lockout
    resp = await client.post("/api/v1/auth/verify-otp", json=verify_payload)
    assert resp.status_code == 400
    assert "Too many failed attempts" in resp.json()["detail"]

    # Clean lockout in Redis to perform real registration verification
    redis_client.delete(f"otp_attempts:registration:{email}")

    # Retrieve valid OTP from Redis
    otp_code = redis_client.get(f"otp:registration:{email}")
    assert otp_code is not None

    verify_payload["otp"] = otp_code
    resp = await client.post("/api/v1/auth/verify-otp", json=verify_payload)
    assert resp.status_code == 200
    assert "verified successfully" in resp.json()["message"]

    # --- HAPPY PATH: Login (Returns HttpOnly Cookie) ---
    resp = await client.post("/api/v1/auth/login", json=login_payload)
    assert resp.status_code == 200
    assert "Login successful" in resp.json()["message"]
    
    # Assert Cookie Attributes
    assert "access_token" in resp.cookies
    set_cookie_header = resp.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie_header
    assert "SameSite=lax" in set_cookie_header or "samesite=lax" in set_cookie_header

    cookies = resp.cookies

    # --- HAPPY PATH: Access Protected Route & Assert Exposure Security ---
    resp = await client.get("/api/v1/users/me", cookies=cookies)
    assert resp.status_code == 200
    profile = resp.json()
    assert profile["email"] == email
    assert profile["full_name"] == "John Doe"
    # Ensure sensitive credentials are never exposed
    assert "security_answer" not in profile
    assert "security_answer_hash" not in profile
    assert "password" not in profile
    assert "hashed_password" not in profile
    assert "id_no" not in profile

    # --- EDGE CASE: Querying Protected Route Without Cookies ---
    client.cookies.clear()
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 401
    assert "Access token missing" in resp.json()["detail"]

    # --- HAPPY PATH: Logout ---
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 200
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
    otp_code = redis_client.get(f"otp:registration:{email}")
    await client.post(
        "/api/v1/auth/verify-otp",
        json={"email": email, "otp": otp_code, "purpose": "registration"}
    )

    # --- EDGE CASE: Forgot Password Wrong Question/Answer ---
    forgot_wrong = {
        "email": email,
        "security_question": SecurityQuestionsSchema.BIRTH_CITY.value,
        "security_answer": "wronganswer",
    }
    resp = await client.post("/api/v1/auth/forgot-password", json=forgot_wrong)
    assert resp.status_code == 200
    assert "password reset code has been sent" in resp.json()["message"]
    # Verify Redis: OTP was NOT generated for invalid credentials
    assert redis_client.get(f"otp:password_reset:{email}") is None

    # --- HAPPY PATH: Forgot Password ---
    forgot_correct = forgot_wrong.copy()
    forgot_correct["security_answer"] = "london"
    resp = await client.post("/api/v1/auth/forgot-password", json=forgot_correct)
    assert resp.status_code == 200
    assert "password reset code has been sent" in resp.json()["message"]

    # --- EDGE CASE: OTP Cooldown ---
    resp = await client.post("/api/v1/auth/forgot-password", json=forgot_correct)
    assert resp.status_code == 200
    assert "password reset code has been sent" in resp.json()["message"]

    # Retrieve Reset OTP from Redis
    reset_otp = redis_client.get(f"otp:password_reset:{email}")
    assert reset_otp is not None

    # Verify Reset OTP (Returns one-time reset token)
    resp = await client.post(
        "/api/v1/auth/verify-otp",
        json={"email": email, "otp": reset_otp, "purpose": "password_reset"}
    )
    assert resp.status_code == 200
    assert "reset_token" in resp.json()
    reset_token = resp.json()["reset_token"]

    # --- EDGE CASE: Reset Confirm Password Mismatch ---
    reset_payload = {
        "email": email,
        "reset_token": reset_token,
        "new_password": "newpassword999",
        "confirm_password": "mismatchedpassword",
    }
    resp = await client.post("/api/v1/auth/reset-password", json=reset_payload)
    assert resp.status_code == 422
    assert "Passwords do not match" in resp.text

    # --- EDGE CASE: Invalid Reset Token ---
    reset_payload_wrong = reset_payload.copy()
    reset_payload_wrong["confirm_password"] = "newpassword999"
    reset_payload_wrong["reset_token"] = "invalid_token_123"
    resp = await client.post("/api/v1/auth/reset-password", json=reset_payload_wrong)
    assert resp.status_code == 400
    assert "Password reset session expired or invalid" in resp.json()["detail"]

    # --- HAPPY PATH: Reset Password Confirm ---
    reset_payload_correct = reset_payload.copy()
    reset_payload_correct["confirm_password"] = "newpassword999"
    resp = await client.post("/api/v1/auth/reset-password", json=reset_payload_correct)
    assert resp.status_code == 200
    assert "successful" in resp.json()["message"]

    # --- EDGE CASE: Reusing Password Reset Token (One-time only check) ---
    resp = await client.post("/api/v1/auth/reset-password", json=reset_payload_correct)
    assert resp.status_code == 400
    assert "Password reset session expired or invalid" in resp.json()["detail"]

    # Verify Login works with the new password
    login_payload = {
        "email": email,
        "password": "newpassword999",
    }
    resp = await client.post("/api/v1/auth/login", json=login_payload)
    assert resp.status_code == 200
