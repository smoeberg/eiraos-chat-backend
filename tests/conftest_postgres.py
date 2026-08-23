"""Shared helpers for Postgres-backed integration tests."""
from __future__ import annotations
import os
import pytest

DEFAULT_TEST_DB = "postgresql+asyncpg://postgres:postgres@localhost:5432/eiraos_test"

def postgres_url() -> str | None:
    url = os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
    if url and url.startswith("postgresql"):
        return url
    if os.environ.get("EIRAOS_USE_LOCAL_PG") == "1":
        return DEFAULT_TEST_DB
    return None

def require_postgres() -> str:
    url = postgres_url()
    if not url:
        pytest.skip("Postgres concurrency tests require DATABASE_URL")
    return url
