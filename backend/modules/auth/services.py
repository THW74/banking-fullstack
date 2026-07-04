import random
import uuid
from datetime import datetime, timezone, timedelta
import jwt
from pwdlib import PasswordHash
import redis

from infrastructure.config import settings

# Initialize password hashing (uses Argon2 internally)
password_hash = PasswordHash.recommended()

# Initialize Redis client for OTP storage
redis_client = redis.from_url(settings.CELERY_RESULT_BACKEND, decode_responses=True)


class AuthService:
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        try:
            return password_hash.verify(plain_password, hashed_password)
        except Exception:
            return False

    def get_password_hash(self, password: str) -> str:
        return password_hash.hash(password)

    def create_access_token(self, subject: str) -> str:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        payload = {
            "sub": subject,
            "exp": expire,
            "iat": datetime.now(timezone.utc),
        }
        return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    def verify_access_token(self, token: str) -> dict:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


class OtpService:
    def generate_otp(self, email: str) -> str:
        otp_code = f"{random.randint(100000, 999999)}"
        redis_client.setex(f"otp:{email}", 300, otp_code)  # 5 minutes TTL
        return otp_code

    def verify_otp(self, email: str, otp: str) -> bool:
        key = f"otp:{email}"
        cached_otp = redis_client.get(key)
        if cached_otp and cached_otp == otp:
            redis_client.delete(key)
            return True
        return False


auth_service = AuthService()
otp_service = OtpService()
