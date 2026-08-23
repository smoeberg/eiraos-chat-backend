from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "EiraOS Chat Backend"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "super-secret-production-key-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/eiraos"
    REDIS_URL: str = "redis://localhost:6379/0"
    OPENAI_API_KEY: Optional[str] = "sk-placeholder"
    ANTHROPIC_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
