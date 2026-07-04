from pydantic import BaseModel, EmailStr, Field, field_validator


class EmailRequestSchema(BaseModel):
    email: EmailStr


class LoginRequestSchema(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=40)


class OTPVerifyRequestSchema(BaseModel):
    email: EmailStr
    otp: str = Field(min_length=6, max_length=6)


class PasswordResetConfirmSchema(BaseModel):
    new_password: str = Field(min_length=8, max_length=40)
    confirm_password: str = Field(min_length=8, max_length=40)

    @field_validator("confirm_password")
    @classmethod
    def validate_password_match(cls, v, values):
        if "new_password" in values.data and v != values.data["new_password"]:
            raise ValueError("Passwords do not match")
        return v
