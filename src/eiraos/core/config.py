from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "EiraOS Chat Backend"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    SECRET_KEY: str = "change-me-in-production-use-a-long-random-string"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_ISSUER: str = "eiraos"
    JWT_AUDIENCE: str = "eiraos-api"

    DATABASE_URL: str = "postgresql+asyncpg://eiraos:eiraos@localhost:5432/eiraos"
    REDIS_URL: str = ""
    # Dev-only: process document ingest inline if ARQ is down
    ALLOW_SYNC_INGEST_FALLBACK: bool = False

    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""

    CORS_ORIGINS: str = "http://localhost:3000"

    RATE_LIMIT_DEFAULT: str = "60/minute"


settings = Settings()
