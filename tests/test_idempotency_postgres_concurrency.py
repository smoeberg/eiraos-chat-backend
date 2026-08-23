"""
Postgres concurrency tests for atomic idempotency.

Requires a live PostgreSQL database:
  export DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/dbname

In CI the workflow starts a Postgres service and sets DATABASE_URL automatically.

What we prove:
  1. N parallel begin_idempotency(same key, same body) → exactly 1 "processing"
  2. The losers get HTTP 409 (in progress) — not a second execution grant
  3. Different body hash with same key → 409 conflict
  4. After complete, replay returns "completed"
  5. Unique constraint holds under concurrent inserts
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from conftest_postgres import require_postgres  # tests/ on pythonpath; not a package install


def _make_request(body: bytes, org_id: int = 1, user_id: int = 1) -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/chat/completions",
        "raw_path": b"/api/v1/chat/completions",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
    }
    request = Request(scope)
    request.state.cached_body = body
    request.state.organization_id = org_id
    request.state.user_id = user_id
    return request
