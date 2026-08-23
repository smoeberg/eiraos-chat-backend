from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional

WELL_KNOWN_SECRETS = {
    "super-secret-production-key-change-me",
    "changeme",
    "change-me",
    "secret",
    "password",
    "",
}
PLACEHOLDER_API_KEYS = {"sk-placeholder", "replace-me", "xxx", ""}


class Settings(BaseSettings):
    PROJECT_NAME: str = "EiraOS Chat Backend"
    APP_ENV: str = "development"  # development | staging | production
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "super-secret-production-key-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_ISSUER: str = "eiraos"
    JWT_AUDIENCE: str = "eiraos-api"
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/eiraos"
    REDIS_URL: str = ""
    # Dev-only: process document ingest inline if ARQ is down (never client-controlled)
    ALLOW_SYNC_INGEST_FALLBACK: bool = False
    OPENAI_API_KEY: Optional[str] = "sk-placeholder"
    ANTHROPIC_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    CORS_ORIGINS: str = "http://localhost:3000"

    @field_validator("SECRET_KEY")
    @classmethod
    def _secret_key_must_not_be_well_known(cls, v, info):
        env = info.data.get("APP_ENV", "development")
        if env not in ("staging", "production"):
            return v
        if not v or v in WELL_KNOWN_SECRETS or len(v) < 32:
            raise ValueError(
                "SECRET_KEY must be a strong, non-default value in "
                f"{env}; refusing well-known placeholder."
            )
        return v

    @field_validator("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")
    @classmethod
    def _api_keys_must_be_real_in_non_dev(cls, v, info):
        env = info.data.get("APP_ENV", "development")
        if env in ("development",) or v is None:
            return v
        if v in PLACEHOLDER_API_KEYS or not isinstance(v, str) or v.strip() == "":
            raise ValueError(
                f"provider API key placeholder rejected in {env}; "
                "set a real key."
            )
        return v

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
