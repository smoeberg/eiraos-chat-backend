"""Canonical ARQ Redis connection settings."""
from __future__ import annotations

from arq.connections import RedisSettings


def redis_settings_from_url(url: str | None) -> RedisSettings:
    normalized = (url or "").strip()
    if not normalized:
        return RedisSettings(host="localhost", port=6379)

    settings = RedisSettings.from_dsn(normalized)
    if settings.ssl:
        settings.ssl_check_hostname = True
    return settings
