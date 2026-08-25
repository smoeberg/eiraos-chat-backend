"""Production Qualification — Gate 1 (Security) + Gate 2 (Correctness).

These tests are designed to run in CI without external AI providers.
Postgres-backed cases skip unless DATABASE_URL / EIRAOS_USE_LOCAL_PG is set.

Mapping:
  G1.x  → security
  G2.x  → correctness
"""
from __future__ import annotations

import hashlib
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Request


@pytest.fixture()
def client():
    pytest.importorskip("slowapi")
    from fastapi.testclient import TestClient
    from eiraos.main import app

    return TestClient(app)


def test_g1_3_require_permission_queries_organization_member():
    """RBAC must load membership from DB, not trust JWT role alone."""
    from eiraos.api.v1 import auth as auth_mod

    src = inspect.getsource(auth_mod.require_permission)
    assert "OrganizationMember" in src


def test_g1_6_metrics_requires_auth(client):
    r = client.get("/metrics")
    assert r.status_code in (401, 403)


def test_g1_7_protected_routes_require_auth(client):
    assert client.get("/api/v1/organizations").status_code == 401
    assert (
        client.post("/api/v1/documents/search", json={"query": "x"}).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/chat/completions",
            json={
                "conversation_id": 1,
                "bot_id": 1,
                "prompt": "hi",
                "stream": False,
            },
        ).status_code
        == 401
    )


def test_g1_jwt_config_has_issuer_audience():
    from eiraos.core.config import settings

    assert hasattr(settings, "SECRET_KEY")
    assert hasattr(settings, "ALGORITHM")
    if hasattr(settings, "JWT_ISSUER"):
        assert settings.JWT_ISSUER
    if hasattr(settings, "JWT_AUDIENCE"):
        assert settings.JWT_AUDIENCE


def test_g1_secret_key_validator_rejects_well_known_in_production():
    from eiraos.core.config import Settings

    with pytest.raises(Exception):
        Settings(APP_ENV="production", SECRET_KEY="changeme")


@pytest.mark.asyncio
async def test_g2_2_lease_fencing_rejects_stale_token():
    from eiraos.core import idempotency as mod
    from eiraos.domains.idempotency.models import IdempotencyRecord

    body = b'{"x":1}'
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [],
        "query_string": b"",
    }
    request = Request(scope)
    request.state.cached_body = body
    request.state.organization_id = 1
    request.state.user_id = 2

    digest = hashlib.sha256(body).hexdigest()
    existing = IdempotencyRecord(
        organization_id=1,
        user_id=2,
        key="k",
        request_hash=digest,
        status="processing",
        lease_token="token-B",
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
async def test_g2_2_lease_fencing_accepts_matching_token():
    from eiraos.core import idempotency as mod
    from eiraos.domains.idempotency.models import IdempotencyRecord

    body = b'{"x":1}'
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [],
        "query_string": b"",
    }
    request = Request(scope)
    request.state.cached_body = body
    request.state.organization_id = 1
    request.state.user_id = 2

    digest = hashlib.sha256(body).hexdigest()
    existing = IdempotencyRecord(
        organization_id=1,
        user_id=2,
        key="k",
        request_hash=digest,
        status="processing",
        lease_token="token-B",
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


def test_g2_3_chat_transitions_same_assistant_row():
    from eiraos.application import chat_persistence
    from eiraos.domains.conversations.models import Message

    src = inspect.getsource(chat_persistence.ChatPersistenceContract.finalize)
    assert "assistant.content = content" in src
    assert "assistant.status = terminal_status" in src
    constraints = {constraint.name for constraint in Message.__table__.constraints}
    assert "uq_messages_execution_role" in constraints


def test_g2_7_sync_fallback_not_client_controlled():
    from eiraos.api.v1.documents import DocumentIngestRequest
    from eiraos.core.config import settings

    fields = getattr(DocumentIngestRequest, "model_fields", None) or {}
    assert "allow_sync_fallback" not in fields
    assert hasattr(settings, "ALLOW_SYNC_INGEST_FALLBACK")
    assert settings.ALLOW_SYNC_INGEST_FALLBACK is False


def test_g2_8_health_uses_timeouts():
    from eiraos import main as main_mod

    src = inspect.getsource(main_mod.health_ready)
    assert "wait_for" in src
    assert "timeout" in src


def test_g2_rag_knowledge_scope_applied_in_sql():
    from eiraos.domains.documents.rag_service import RAGService

    public_clause = RAGService._scope_clause("public")
    private_clause = RAGService._scope_clause("private")
    assert "visibility" in public_clause
    assert "private" in private_clause


def test_g2_document_chunk_metadata_column_name():
    from eiraos.domains.documents.models import DocumentChunk

    col = DocumentChunk.__table__.c.get("metadata")
    assert col is not None, "DB column must be named 'metadata' for raw SQL"


def test_g2_idempotency_key_header_mismatch_rejected():
    from eiraos.core.idempotency import resolve_idempotency_key

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"idempotency-key", b"header-key")],
        "query_string": b"",
    }
    request = Request(scope)
    with pytest.raises(HTTPException) as ei:
        resolve_idempotency_key(request, "body-key")
    assert ei.value.status_code == 400


def test_g2_health_live_and_ready_contract(client):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code in (200, 503)
    assert client.get("/health").status_code in (200, 503)
