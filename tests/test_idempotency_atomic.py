"""C1-01: Idempotency atomicity, lease, hash conflict."""
from __future__ import annotations

import inspect
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException


def test_idempotency_module_uses_on_conflict():
    import eiraos.core.idempotency as mod
    src = inspect.getsource(mod.begin_idempotency)
    assert "on_conflict_do_nothing" in src
    assert "with_for_update" in src
    assert "lease_until" in src


def test_idempotency_model_has_lease_and_unique():
    from eiraos.domains.idempotency.models import IdempotencyRecord
    cols = {c.name for c in IdempotencyRecord.__table__.columns}
    assert "lease_until" in cols
    names = [getattr(u, "name", None) for u in IdempotencyRecord.__table__.constraints]
    assert "uq_idempotency_org_user_key" in names


def test_body_digest_stable():
    from eiraos.core.idempotency import _body_digest
    from fastapi import Request
    scope = {"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""}
    request = Request(scope)
    request.state.cached_body = b'{"a":1}'
    assert _body_digest(request) == hashlib.sha256(b'{"a":1}').hexdigest()


@pytest.mark.asyncio
async def test_begin_requires_auth_context():
    from eiraos.core.idempotency import begin_idempotency
    from fastapi import Request
    scope = {"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""}
    request = Request(scope)
    request.state.cached_body = b"{}"
    with pytest.raises(HTTPException) as ei:
        await begin_idempotency(AsyncMock(), request, "k1")
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_begin_insert_wins_returns_processing():
    from eiraos.core import idempotency as mod
    from fastapi import Request
    scope = {"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""}
    request = Request(scope)
    request.state.cached_body = b'{"x":1}'
    request.state.organization_id = 10
    request.state.user_id = 20
    db = AsyncMock()
    insert_result = MagicMock()
    insert_result.scalar_one_or_none.return_value = 42
    db.execute = AsyncMock(return_value=insert_result)
    db.commit = AsyncMock()
    assert await mod.begin_idempotency(db, request, "job-1") == "processing"


@pytest.mark.asyncio
async def test_begin_conflict_different_hash_raises_409():
    from eiraos.core import idempotency as mod
    from eiraos.domains.idempotency.models import IdempotencyRecord
    from fastapi import Request
    scope = {"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""}
    request = Request(scope)
    request.state.cached_body = b'{"new":true}'
    request.state.organization_id = 1
    request.state.user_id = 2
    insert_result = MagicMock()
    insert_result.scalar_one_or_none.return_value = None
    existing = IdempotencyRecord(
        organization_id=1, user_id=2, key="k", request_hash="deadbeef",
        status="completed", response_reference="{}",
    )
    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = existing
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[insert_result, select_result])
    db.commit = AsyncMock()
    with pytest.raises(HTTPException) as ei:
        await mod.begin_idempotency(db, request, "k")
    assert ei.value.status_code == 409


def test_documents_ingest_never_uses_none_key():
    from pathlib import Path
    src = Path("src/eiraos/api/v1/documents.py").read_text()
    assert "doc:ingest:" in src
    assert "if ledger_key" in src or "if idem_key" in src
    assert "doc:ingest:None" not in src


def test_worker_sets_processing_and_ready():
    import eiraos.workers.tasks as tasks
    src = inspect.getsource(tasks.process_document_ingestion)
    assert 'doc.status = "processing"' in src
    assert "intelligent_chunking" in src
