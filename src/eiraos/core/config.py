from pydantic_settings import BaseSettings
from pydantic import Field, field_validator, model_validator
from typing import Optional
from urllib.parse import urlsplit
from ipaddress import ip_network

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
    RELEASE_SHA: str = Field(default="development", pattern=r"^[A-Za-z0-9._-]{1,64}$")
    APP_ENV: str = "development"  # development | staging | production
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "super-secret-production-key-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60, ge=1, le=1440)
    JWT_ISSUER: str = "eiraos"
    JWT_AUDIENCE: str = "eiraos-api"
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/eiraos"
    REDIS_URL: str = ""
    EXECUTION_BUDGET_MAX_COST: float = 20000.0
    USER_BUDGET_REMAINING: float | None = None
    ORGANIZATION_BUDGET_REMAINING: float | None = None
    CHAT_PROVIDER_TIMEOUT_SECONDS: float = Field(default=60.0, gt=0)
    PROVIDER_HTTP_MAX_ATTEMPTS: int = Field(default=2, ge=1, le=3)
    PROVIDER_HTTP_BACKOFF_SECONDS: float = Field(default=0.1, ge=0, le=2)
    PROVIDER_HTTP_MAX_RETRY_AFTER_SECONDS: float = Field(default=2.0, ge=0, le=10)
    CHAT_MAX_ATTEMPTS: int = Field(default=3, ge=1, le=10)
    ALLOW_PUBLIC_REGISTER: bool = False
    # Dev-only: process document ingest inline if ARQ is down (never client-controlled)
    ALLOW_SYNC_INGEST_FALLBACK: bool = False
    STORAGE_ROOT: str = "storage/uploads"
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    CORS_ORIGINS: str = "http://localhost:3000"
    TRUSTED_HOSTS: str = "localhost,127.0.0.1,testserver"
    TRUSTED_PROXY_CIDRS: str = "127.0.0.1/32"
    MAX_REQUEST_BODY_BYTES: int = Field(default=2 * 1024 * 1024, ge=1024, le=20 * 1024 * 1024)
    MAX_UPLOAD_REQUEST_BODY_BYTES: int = Field(
        default=11 * 1024 * 1024, ge=1024, le=20 * 1024 * 1024
    )

    @field_validator("APP_ENV")
    @classmethod
    def _environment_must_be_known(cls, value):
        if value not in {"development", "staging", "production"}:
            raise ValueError("APP_ENV must be development, staging or production")
        return value

    @field_validator("ALGORITHM")
    @classmethod
    def _jwt_algorithm_must_be_symmetric_and_explicit(cls, value):
        if value not in {"HS256", "HS384", "HS512"}:
            raise ValueError("ALGORITHM must be HS256, HS384 or HS512")
        return value

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
        if isinstance(v, str) and not v.strip():
            return None
        env = info.data.get("APP_ENV", "development")
        if env in ("development",) or v is None:
            return v
        if v in PLACEHOLDER_API_KEYS or not isinstance(v, str) or v.strip() == "":
            raise ValueError(
                f"provider API key placeholder rejected in {env}; "
                "set a real key."
            )
        return v

    @model_validator(mode="after")
    def _production_ingress_must_fail_closed(self):
        origins = self.cors_origins
        hosts = self.trusted_hosts
        try:
            proxy_networks = self.trusted_proxy_networks
        except ValueError as exc:
            raise ValueError("trusted proxy CIDRs must be valid IP networks") from exc
        if not origins:
            raise ValueError("at least one CORS origin is required")
        if not hosts:
            raise ValueError("at least one trusted host is required")
        if self.APP_ENV == "production":
            if not self.REDIS_URL:
                raise ValueError("production requires Redis-backed rate limiting")
            if urlsplit(self.REDIS_URL).scheme not in {"redis", "rediss"}:
                raise ValueError("production Redis URL must use redis:// or rediss://")
            if self.ALLOW_SYNC_INGEST_FALLBACK:
                raise ValueError("synchronous ingest fallback is forbidden in production")
            if any(not _secure_origin(origin) for origin in origins):
                raise ValueError("production CORS origins must be explicit HTTPS origins")
            if any(not _public_host(host) for host in hosts):
                raise ValueError("production trusted hosts must be explicit public hosts")
            if not proxy_networks:
                raise ValueError("production requires explicit trusted proxy CIDRs")
            if any(network.prefixlen == 0 for network in proxy_networks):
                raise ValueError("production trusted proxy CIDRs cannot trust every address")
        return self

    @property
    def cors_origins(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.strip() for item in self.CORS_ORIGINS.split(",") if item.strip()))

    @property
    def trusted_hosts(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.strip().lower() for item in self.TRUSTED_HOSTS.split(",") if item.strip()))

    @property
    def trusted_proxy_networks(self):
        return tuple(dict.fromkeys(
            ip_network(item.strip(), strict=False)
            for item in self.TRUSTED_PROXY_CIDRS.split(",") if item.strip()
        ))

    class Config:
        env_file = ".env"
        extra = "ignore"


def _secure_origin(origin: str) -> bool:
    parsed = urlsplit(origin)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
        and "localhost" not in parsed.hostname
        and parsed.hostname not in {"127.0.0.1", "::1"}
    )


def _public_host(host: str) -> bool:
    return (
        bool(host)
        and "*" not in host
        and "://" not in host
        and "/" not in host
        and not any(char.isspace() for char in host)
        and "localhost" not in host
        and host not in {"127.0.0.1", "::1", "testserver"}
    )


settings = Settings()
