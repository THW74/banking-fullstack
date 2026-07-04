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
    EmailRequestSchema,
    PasswordResetConfirmSchema,
)
from .services import auth_service, otp_service, redis_client
from .dependencies import ACCESS_TOKEN_COOKIE

router = APIRouter()


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

    # Hash password & create user (inactive by default)
    hashed_pwd = auth_service.get_password_hash(user_in.password)
    user = await user_service.create_user(db, user_in, hashed_pwd)

    # Generate OTP and send email in background
    otp_code = otp_service.generate_otp(user.email)
    send_otp_email_task.delay(user.email, otp_code)

    return {
        "message": "User registered successfully. Please verify your account with the OTP sent to your email."
    }


@router.post("/verify-otp")
async def verify_otp(
    payload: OTPVerifyRequestSchema,
    db: AsyncSession = Depends(get_session)
):
    is_valid = otp_service.verify_otp(payload.email, payload.otp)
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

    if user.account_status == AccountStatusSchema.INACTIVE:
        # Registration verification path
        user.is_active = True
        user.account_status = AccountStatusSchema.ACTIVE
        db.add(user)
        await db.commit()
        return {"message": "Account verified successfully. You can now login."}
    else:
        # Password reset verification path (sets reset authorization token in Redis)
        redis_client.setex(f"reset_token:{payload.email}", 300, "verified")
        return {"message": "OTP verified successfully. You can now reset your password."}


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
    payload: EmailRequestSchema,
    db: AsyncSession = Depends(get_session)
):
    user = await user_service.get_by_email(db, payload.email)
    if user:
        otp_code = otp_service.generate_otp(user.email)
        send_otp_email_task.delay(user.email, otp_code)

    # We return success message unconditionally to prevent user enumeration
    return {
        "message": "If the email is registered, a password reset code has been sent."
    }


@router.post("/reset-password")
async def reset_password(
    email: str,
    payload: PasswordResetConfirmSchema,
    db: AsyncSession = Depends(get_session)
):
    # Check if reset token exists in Redis
    reset_key = f"reset_token:{email}"
    reset_auth = redis_client.get(reset_key)
    if not reset_auth:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password reset session expired or invalid. Please verify OTP first."
        )

    user = await user_service.get_by_email(db, email)
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

    # Clear reset token from Redis
    redis_client.delete(reset_key)

    return {"message": "Password reset successful."}
