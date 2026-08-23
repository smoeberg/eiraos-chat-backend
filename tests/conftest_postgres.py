"""Shared helpers for Postgres-backed integration tests."""
from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest

# Default CI URL (matches updated workflow). Override with DATABASE_URL.
DEFAULT_TEST_DB = "postgresql+asyncpg://postgres:postgres@localhost:5432/eiraos_test"


def postgres_url() -> str | None:
    url = os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
    if url and url.startswith("postgresql"):
        return url
    # Optional local default — only used when EIRAOS_USE_LOCAL_PG=1
    if os.environ.get("EIRAOS_USE_LOCAL_PG") == "1":
        return DEFAULT_TEST_DB
    return None


def require_postgres() -> str:
    url = postgres_url()
    if not url:
        pytest.skip(
            "Postgres concurrency tests require DATABASE_URL "
            "(postgresql+asyncpg://...). Set EIRAOS_USE_LOCAL_PG=1 for local default."
        )
    return url
