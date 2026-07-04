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
    def generate_otp(self, email: str, purpose: str) -> str:
        import secrets

        # Check cooldown (60s limit)
        cooldown_key = f"otp_cooldown:{purpose}:{email}"
        if redis_client.exists(cooldown_key):
            raise ValueError("cooldown")

        # Generate cryptographically secure OTP
        otp_code = f"{secrets.randbelow(1_000_000):06d}"
        
        # Save OTP in Redis (5-minute TTL)
        redis_client.set(f"otp:{purpose}:{email}", otp_code, ex=300)
        # Set cooldown timer
        redis_client.set(cooldown_key, "1", ex=60)
        return otp_code

    def verify_otp(self, email: str, purpose: str, otp: str) -> bool:
        attempts_key = f"otp_attempts:{purpose}:{email}"

        # Check lockout (max 5 failed attempts)
        attempts = redis_client.get(attempts_key)
        if attempts and int(attempts) >= 5:
            raise ValueError("lockout")

        otp_key = f"otp:{purpose}:{email}"
        cached_otp = redis_client.get(otp_key)

        if cached_otp and cached_otp == otp:
            # Successful verification: clear OTP and attempts
            redis_client.delete(otp_key)
            redis_client.delete(attempts_key)
            return True

        # Failed attempt: increment and set TTL if new
        redis_client.incr(attempts_key)
        redis_client.expire(attempts_key, 300)
        return False


auth_service = AuthService()
otp_service = OtpService()
