"""
Postgres concurrency tests for atomic idempotency.

Requires a live PostgreSQL database:
  export DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/dbname

In CI the workflow starts a Postgres service and sets DATABASE_URL automatically.
"""
from __future__ import annotations

import asyncio
import hashlib
import os

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from conftest_postgres import require_postgres


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
                lease_token VARCHAR(64),
                CONSTRAINT uq_idempotency_org_user_key
                    UNIQUE (organization_id, user_id, key)
            )
        """))
        await conn.execute(text("""
            DO $$ BEGIN
                ALTER TABLE idempotency_records
                    ADD COLUMN IF NOT EXISTS lease_until TIMESTAMP WITHOUT TIME ZONE;
            EXCEPTION WHEN duplicate_column THEN NULL;
            END $$
        """))
        await conn.execute(text("""
            DO $$ BEGIN
                ALTER TABLE idempotency_records
                    ADD COLUMN IF NOT EXISTS lease_token VARCHAR(64);
            EXCEPTION WHEN duplicate_column THEN NULL;
            END $$
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
                return ("ok", result.status, result.lease_token)
            except HTTPException as e:
                return ("http", e.status_code, e.detail)
            except Exception as e:
                return ("err", type(e).__name__, str(e))

    results = await asyncio.gather(*[attempt() for _ in range(n)])

    processing = [r for r in results if r[0] == "ok" and r[1] == "processing"]
    conflicts = [r for r in results if r[0] == "http" and r[1] == 409]
    errors = [r for r in results if r[0] == "err"]

    assert not errors, f"unexpected errors: {errors}"
    assert len(processing) == 1, (
        f"expected exactly 1 processing, got {len(processing)}; full={results}"
    )
    assert len(conflicts) == n - 1, (
        f"expected {n - 1} conflicts, got {len(conflicts)}; full={results}"
    )

    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, request_hash FROM idempotency_records "
                    "WHERE organization_id=:o AND user_id=:u AND key=:k"
                ),
                {"o": org_id, "u": user_id, "k": key},
            )
        ).first()
    assert row is not None
    assert row.status == "processing"
    assert row.request_hash == hashlib.sha256(body).hexdigest()


@pytest.mark.asyncio
async def test_different_payload_same_key_conflicts(session_factory):
    from eiraos.core.idempotency import begin_idempotency, complete_idempotency

    key = f"conc-{os.getpid()}-hash-mismatch"
    org_id, user_id = 42, 8
    await _clean_key(session_factory, org_id, user_id, key)

    req1 = _make_request(b'{"a":1}', org_id=org_id, user_id=user_id)
    async with session_factory() as session:
        outcome = await begin_idempotency(session, req1, key)
        assert outcome.status == "processing"
        await complete_idempotency(
            session, req1, key, 200, '{"ok":true}', lease_token=outcome.lease_token
        )

    req2 = _make_request(b'{"a":2}', org_id=org_id, user_id=user_id)
    async with session_factory() as session:
        with pytest.raises(HTTPException) as ei:
            await begin_idempotency(session, req2, key)
        assert ei.value.status_code == 409
        assert "different payload" in ei.value.detail.lower()


@pytest.mark.asyncio
async def test_completed_replay_after_finish(session_factory):
    from eiraos.core.idempotency import (
        begin_idempotency,
        complete_idempotency,
        read_cached_response,
    )

    key = f"conc-{os.getpid()}-replay"
    body = b'{"replay":true}'
    org_id, user_id = 42, 9
    await _clean_key(session_factory, org_id, user_id, key)

    req = _make_request(body, org_id=org_id, user_id=user_id)
    async with session_factory() as session:
        outcome = await begin_idempotency(session, req, key)
        assert outcome.status == "processing"
        await complete_idempotency(
            session, req, key, 200, '{"assistant":"hi"}',
            lease_token=outcome.lease_token,
        )

    async def replay():
        r = _make_request(body, org_id=org_id, user_id=user_id)
        async with session_factory() as session:
            return await begin_idempotency(session, r, key)

    outcomes = await asyncio.gather(*[replay() for _ in range(8)])
    assert all(getattr(o, "status", o) == "completed" for o in outcomes), outcomes

    async with session_factory() as session:
        cached = await read_cached_response(
            session, _make_request(body, org_id=org_id, user_id=user_id), key
        )
    assert cached == '{"assistant":"hi"}'


@pytest.mark.asyncio
async def test_stale_lease_allows_reclaim(session_factory):
    from eiraos.core.idempotency import begin_idempotency

    key = f"conc-{os.getpid()}-stale"
    body = b'{"stale":true}'
    org_id, user_id = 42, 10
    await _clean_key(session_factory, org_id, user_id, key)

    req = _make_request(body, org_id=org_id, user_id=user_id)
    async with session_factory() as session:
        assert (await begin_idempotency(session, req, key)).status == "processing"
        await session.execute(
            text(
                "UPDATE idempotency_records SET lease_until = NOW() - INTERVAL '5 minutes' "
                "WHERE organization_id=:o AND user_id=:u AND key=:k"
            ),
            {"o": org_id, "u": user_id, "k": key},
        )
        await session.commit()

    req2 = _make_request(body, org_id=org_id, user_id=user_id)
    async with session_factory() as session:
        status = await begin_idempotency(session, req2, key)
    assert status.status == "processing"


@pytest.mark.asyncio
async def test_reclaimed_lease_fences_stale_worker(session_factory):
    """A stale owner cannot renew or complete after another worker reclaims its lease."""
    from eiraos.core.idempotency import (
        begin_idempotency,
        complete_idempotency,
        renew_idempotency_lease,
    )

    key = f"conc-{os.getpid()}-fencing"
    body = b'{"fencing":true}'
    org_id, user_id = 42, 11
    await _clean_key(session_factory, org_id, user_id, key)

    req_a = _make_request(body, org_id=org_id, user_id=user_id)
    async with session_factory() as session:
        outcome_a = await begin_idempotency(session, req_a, key)
    assert outcome_a.status == "processing"
    assert outcome_a.lease_token

    # Force the first lease to expire, then let a second transaction reclaim it.
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE idempotency_records SET lease_until = NOW() - INTERVAL '5 minutes' "
                "WHERE organization_id=:o AND user_id=:u AND key=:k"
            ),
            {"o": org_id, "u": user_id, "k": key},
        )
        await session.commit()

    req_b = _make_request(body, org_id=org_id, user_id=user_id)
    async with session_factory() as session:
        outcome_b = await begin_idempotency(session, req_b, key)
    assert outcome_b.status == "processing"
    assert outcome_b.lease_token
    assert outcome_b.lease_token != outcome_a.lease_token

    async with session_factory() as session:
        assert not await renew_idempotency_lease(
            session, req_a, key, outcome_a.lease_token
        )

    async with session_factory() as session:
        assert await renew_idempotency_lease(
            session, req_b, key, outcome_b.lease_token
        )

    async with session_factory() as session:
        assert not await complete_idempotency(
            session, req_a, key, 200, '{"owner":"stale"}',
            lease_token=outcome_a.lease_token,
        )

    async with session_factory() as session:
        assert await complete_idempotency(
            session, req_b, key, 200, '{"owner":"current"}',
            lease_token=outcome_b.lease_token,
        )

    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, response_reference, lease_token "
                    "FROM idempotency_records "
                    "WHERE organization_id=:o AND user_id=:u AND key=:k"
                ),
                {"o": org_id, "u": user_id, "k": key},
            )
        ).first()
    assert row is not None
    assert row.status == "completed"
    assert row.response_reference == '{"owner":"current"}'
    assert row.lease_token == outcome_b.lease_token
