"""Lease-token fencing: stale workers must not overwrite reclaimed results."""
from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request

from eiraos.domains.idempotency.models import IdempotencyRecord


def _req(body: bytes = b"{}", org: int = 1, user: int = 2) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [],
        "query_string": b"",
    }
    request = Request(scope)
    request.state.cached_body = body
    request.state.organization_id = org
    request.state.user_id = user
    return request


def test_model_has_lease_token():
    cols = {c.name for c in IdempotencyRecord.__table__.columns}
    assert "lease_token" in cols


def test_begin_returns_outcome_with_token():
    from eiraos.core.idempotency import IdempotencyOutcome
    o = IdempotencyOutcome("processing", "abc")
    assert o == "processing"
    assert o.lease_token == "abc"


@pytest.mark.asyncio
async def test_complete_rejects_stale_token():
    from eiraos.core import idempotency as mod
    body = b'{"x":1}'
    request = _req(body)
    digest = hashlib.sha256(body).hexdigest()
    existing = IdempotencyRecord(
        organization_id=1, user_id=2, key="k", request_hash=digest,
        status="processing", lease_token="token-B",
    )
    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = existing
    db = AsyncMock()
    db.execute = AsyncMock(return_value=select_result)
    db.commit = AsyncMock()
    ok = await mod.complete_idempotency(
        db, request, "k", 200, '{"from":"A"}', lease_token="token-A"
    )
    assert ok is False
    assert existing.response_reference is None


@pytest.mark.asyncio
async def test_complete_accepts_matching_token():
    from eiraos.core import idempotency as mod
    body = b'{"x":1}'
    request = _req(body)
    digest = hashlib.sha256(body).hexdigest()
    existing = IdempotencyRecord(
        organization_id=1, user_id=2, key="k", request_hash=digest,
        status="processing", lease_token="token-B",
    )
    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = existing
    db = AsyncMock()
    db.execute = AsyncMock(return_value=select_result)
    db.commit = AsyncMock()
    ok = await mod.complete_idempotency(
        db, request, "k", 200, '{"from":"B"}', lease_token="token-B"
    )
    assert ok is True
    assert existing.status == "completed"
    assert existing.response_reference == '{"from":"B"}'


def test_resolve_key_mismatch_raises():
    from eiraos.core.idempotency import resolve_idempotency_key
    from fastapi import HTTPException
    scope = {
        "type": "http", "method": "POST", "path": "/",
        "headers": [(b"idempotency-key", b"header-key")],
        "query_string": b"",
    }
    request = Request(scope)
    with pytest.raises(HTTPException) as ei:
        resolve_idempotency_key(request, "body-key")
    assert ei.value.status_code == 400


def test_resolve_key_header_wins():
    from eiraos.core.idempotency import resolve_idempotency_key
    scope = {
        "type": "http", "method": "POST", "path": "/",
        "headers": [(b"idempotency-key", b"same")],
        "query_string": b"",
    }
    request = Request(scope)
    assert resolve_idempotency_key(request, "same") == "same"
    assert resolve_idempotency_key(request, None) == "same"
