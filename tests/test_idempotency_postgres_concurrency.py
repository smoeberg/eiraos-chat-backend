"""Postgres concurrency tests for atomic idempotency.

Requires DATABASE_URL=postgresql+asyncpg://user:pass@host/db
"""
from __future__ import annotations

import asyncio
import hashlib
import os

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.conftest_postgres import require_postgres


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
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
    }
    request = Request(scope)
    request.state.cached_body = body
    request.state.organization_id = org_id
    request.state.user_id = user_id
    return request


@pytest.fixture
async def pg_engine():
    url = require_postgres()
    engine = create_async_engine(url, echo=False, pool_size=20, max_overflow=10)
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS idempotency_records (
                id SERIAL PRIMARY KEY,
                organization_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                key VARCHAR(128) NOT NULL,
                request_hash VARCHAR(64) NOT NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'processing',
                response_status INTEGER,
                response_reference TEXT,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP WITHOUT TIME ZONE,
                lease_until TIMESTAMP WITHOUT TIME ZONE,
                CONSTRAINT uq_idempotency_org_user_key
                    UNIQUE (organization_id, user_id, key)
            )
        """))
        await conn.execute(text("""
            DO $$ BEGIN
                ALTER TABLE idempotency_records
                    ADD COLUMN IF NOT EXISTS lease_until TIMESTAMP WITHOUT TIME ZONE;
            EXCEPTION WHEN duplicate_column THEN NULL;
            END $$;
        """))
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(pg_engine):
    return async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)


async def _clean_key(session_factory, org_id: int, user_id: int, key: str):
    async with session_factory() as session:
        await session.execute(
            text(
                "DELETE FROM idempotency_records "
                "WHERE organization_id = :o AND user_id = :u AND key = :k"
            ),
            {"o": org_id, "u": user_id, "k": key},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_concurrent_begin_only_one_processing(session_factory):
    from eiraos.core.idempotency import begin_idempotency

    key = f"conc-{os.getpid()}-one-winner"
    body = b'{"prompt":"hello","stream":false}'
    org_id, user_id = 42, 7
    await _clean_key(session_factory, org_id, user_id, key)

    n = 16

    async def attempt():
        request = _make_request(body, org_id=org_id, user_id=user_id)
        async with session_factory() as session:
            try:
                result = await begin_idempotency(session, request, key)
                return ("ok", result)
            except HTTPException as e:
                return ("http", e.status_code, e.detail)
            except Exception as e:
                return ("err", type(e).__name__, str(e))

    results = await asyncio.gather(*[attempt() for _ in range(n)])
    processing = [r for r in results if r == ("ok", "processing")]
    conflicts = [r for r in results if r[0] == "http" and r[1] == 409]
    errors = [r for r in results if r[0] == "err"]

    assert not errors, f"unexpected errors: {errors}"
    assert len(processing) == 1, f"expected 1 processing, got {len(processing)}; {results}"
    assert len(conflicts) == n - 1, f"expected {n-1} conflicts, got {len(conflicts)}"


@pytest.mark.asyncio
async def test_different_payload_same_key_conflicts(session_factory):
    from eiraos.core.idempotency import begin_idempotency, complete_idempotency

    key = f"conc-{os.getpid()}-hash-mismatch"
    org_id, user_id = 42, 8
    await _clean_key(session_factory, org_id, user_id, key)

    req1 = _make_request(b'{"a":1}', org_id=org_id, user_id=user_id)
    async with session_factory() as session:
        assert await begin_idempotency(session, req1, key) == "processing"
        await complete_idempotency(session, req1, key, 200, '{"ok":true}')

    req2 = _make_request(b'{"a":2}', org_id=org_id, user_id=user_id)
    async with session_factory() as session:
        with pytest.raises(HTTPException) as ei:
            await begin_idempotency(session, req2, key)
        assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_completed_replay_after_finish(session_factory):
    from eiraos.core.idempotency import begin_idempotency, complete_idempotency

    key = f"conc-{os.getpid()}-replay"
    body = b'{"replay":true}'
    org_id, user_id = 42, 9
    await _clean_key(session_factory, org_id, user_id, key)

    req = _make_request(body, org_id=org_id, user_id=user_id)
    async with session_factory() as session:
        assert await begin_idempotency(session, req, key) == "processing"
        await complete_idempotency(session, req, key, 200, '{"assistant":"hi"}')

    async def replay():
        r = _make_request(body, org_id=org_id, user_id=user_id)
        async with session_factory() as session:
            return await begin_idempotency(session, r, key)

    outcomes = await asyncio.gather(*[replay() for _ in range(8)])
    assert all(o == "completed" for o in outcomes), outcomes
