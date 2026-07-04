import secrets
from typing import Protocol, cast
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.config import settings
from infrastructure.database import get_session
from infrastructure.tasks import send_otp_email_task
from modules.users.models import User
from modules.users.schemas import UserCreateSchema, AccountStatusSchema
from modules.users.services import user_service
from .schemas import (
    LoginRequestSchema,
    OTPVerifyRequestSchema,
    ForgotPasswordRequestSchema,
    PasswordResetConfirmSchema,
)
from .services import auth_service, otp_service, redis_client
from .dependencies import ACCESS_TOKEN_COOKIE

router = APIRouter()


class DelayedTask(Protocol):
    def delay(self, *args: object, **kwargs: object) -> object:
        ...


send_otp_email = cast(DelayedTask, send_otp_email_task)


@router.post("/register")
async def register(
    user_in: UserCreateSchema,
    db: AsyncSession = Depends(get_session)
):
    # Check duplicate email
    existing_user = await user_service.get_by_email(db, user_in.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Check duplicate username
    if user_in.username:
        result = await db.execute(select(User).where(User.username == user_in.username))
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken"
            )

    # Check duplicate ID No
    result = await db.execute(select(User).where(User.id_no == user_in.id_no))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Identification number already registered"
        )

    # Hash password & security answer, then create user (inactive by default)
    hashed_pwd = auth_service.get_password_hash(user_in.password)
    security_hash = auth_service.get_password_hash(user_in.security_answer.strip().lower())
    
    user = await user_service.create_user(db, user_in, hashed_pwd, security_hash)

    # Generate OTP (registration scope) and send email in background
    try:
        otp_code = otp_service.generate_otp(user.email, "registration")
    except ValueError as e:
        if str(e) == "cooldown":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Please wait 60 seconds before requesting another OTP."
            )
        raise

    send_otp_email.delay(user.email, otp_code)

    return {
        "message": "User registered successfully. Please verify your account with the OTP sent to your email."
    }


@router.post("/verify-otp")
async def verify_otp(
    payload: OTPVerifyRequestSchema,
    db: AsyncSession = Depends(get_session)
):
    try:
        is_valid = otp_service.verify_otp(payload.email, payload.purpose, payload.otp)
    except ValueError as e:
        if str(e) == "lockout":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Too many failed attempts. Please request a new OTP."
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OTP"
        )

    user = await user_service.get_by_email(db, payload.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if payload.purpose == "registration":
        if user.account_status == AccountStatusSchema.INACTIVE:
            user.is_active = True
            user.account_status = AccountStatusSchema.ACTIVE
            db.add(user)
            await db.commit()
            return {"message": "Account verified successfully. You can now login."}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Account is already verified."
            )
    else:  # password_reset
        # Generate one-time secure random reset token
        reset_token = secrets.token_urlsafe(32)
        # Store hashed reset token in Redis (5-minute TTL)
        token_hash = auth_service.get_password_hash(reset_token)
        redis_client.set(f"reset_token:{payload.email}", token_hash, ex=300)
        return {
            "message": "OTP verified successfully. Use the reset token to complete password reset.",
            "reset_token": reset_token
        }


@router.post("/login")
async def login(
    credentials: LoginRequestSchema,
    response: Response,
    db: AsyncSession = Depends(get_session)
):
    user = await user_service.get_by_email(db, credentials.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect email or password"
        )

    is_verified = auth_service.verify_password(credentials.password, user.hashed_password)
    if not is_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect email or password"
        )

    if not user.is_active or user.account_status != AccountStatusSchema.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account is pending verification. Please verify your OTP first."
        )

    # Set HttpOnly Cookie containing the token
    token = auth_service.create_access_token(str(user.id))
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    return {"message": "Login successful"}


@router.post("/logout")
async def logout(response: Response):
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value="",
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=0,
    )
    return {"message": "Logout successful"}


@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequestSchema,
    db: AsyncSession = Depends(get_session)
):
    user = await user_service.get_by_email(db, payload.email)
    
    credentials_valid = False
    if user:
        # Verify security question and answer
        if (
            user.security_question == payload.security_question
            and auth_service.verify_password(payload.security_answer.strip().lower(), user.security_answer_hash)
        ):
            credentials_valid = True
    else:
        # Mitigate timing attack by executing a dummy verify_password
        auth_service.verify_password("dummy_password", "$argon2id$v=19$m=65536,t=3,p=4$wohoKJ67pqR/zn3yqUMD/A$nWq8jMuzkbatvqUg68mixyZqicD9+5+BP54GB/KvKv8")

    if credentials_valid and user:
        # Generate password_reset scope OTP
        try:
            otp_code = otp_service.generate_otp(user.email, "password_reset")
            send_otp_email.delay(user.email, otp_code)
        except ValueError:
            # Even if cooldown throws, return 200 to prevent timing-based validation leaks
            pass

    return {
        "message": "If the email is registered and credentials match, a password reset code has been sent."
    }


@router.post("/reset-password")
async def reset_password(
    payload: PasswordResetConfirmSchema,
    db: AsyncSession = Depends(get_session)
):
    # Check if reset token exists in Redis
    reset_key = f"reset_token:{payload.email}"
    cached_hash = redis_client.get(reset_key)
    if not isinstance(cached_hash, str) or not auth_service.verify_password(payload.reset_token, cached_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password reset session expired or invalid. Please verify OTP first."
        )

    user = await user_service.get_by_email(db, payload.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Update password and activate user if locked
    user.hashed_password = auth_service.get_password_hash(payload.new_password)
    if user.account_status == AccountStatusSchema.LOCKED:
        user.account_status = AccountStatusSchema.ACTIVE
        user.is_active = True

    db.add(user)
    await db.commit()

    # Clear reset token from Redis (ensures one-time use)
    redis_client.delete(reset_key)

    return {"message": "Password reset successful."}
