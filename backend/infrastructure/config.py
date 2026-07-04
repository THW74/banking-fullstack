import os
import pathlib
from typing import Literal
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_env = os.getenv("ENVIRONMENT", "local")


class Settings(BaseSettings):
    ENVIRONMENT: Literal["local", "dev", "prod"] = "local"
 
    model_config = SettingsConfigDict(
        env_file=pathlib.Path(__file__).parent.parent / f".env.{_env}",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str
    PROJECT_DESCRIPTION: str
    API_V1_STR: str
    SITE_NAME: str

    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "banking"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: str | None = None

    CELERY_BROKER_URL: str = "amqp://guest:guest@localhost:5672//"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None

    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    COOKIE_SECURE: bool = True

    @model_validator(mode="before")
    @classmethod
    def remove_empty_strings(cls, values: dict) -> dict:
        if isinstance(values, dict):
            return {k: v for k, v in values.items() if v != ""}
        return values

    @model_validator(mode="after")
    def assemble_settings(self) -> "Settings":
        if (
            not self.DATABASE_URL 
            or "${" in self.DATABASE_URL 
            or self.DATABASE_URL.strip() in ("", "postgresql+asyncpg://:@:/")
        ):
            self.DATABASE_URL = f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

        if not getattr(self, "JWT_SECRET_KEY", None) or self.JWT_SECRET_KEY.strip() in (
            "secret-key-placeholder-change-in-production",
            "change-me",
            "",
        ):
            raise ValueError(
                "JWT_SECRET_KEY is insecure or missing! Please set a secure key in the environment."
            )
        return self


settings = Settings()  # pyright: ignore [reportCallIssue]