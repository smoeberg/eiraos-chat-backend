"""Regression tests for tenant and private-document RAG isolation."""
from types import SimpleNamespace

import pytest

from eiraos.domains.documents.rag_service import RAGService


class FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchall(self):
        return self._rows


class CapturingDB:
    def __init__(self):
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((str(statement), dict(params)))
        return FakeResult()


@pytest.mark.asyncio
async def test_private_scope_requires_verified_user_context():
    db = CapturingDB()

    with pytest.raises(PermissionError, match="verified user context"):
        await RAGService.hybrid_search(
            db=db,
            organization_id=10,
            query_embedding=[0.0, 0.0],
            query_text="private document",
            knowledge_scope="private",
            caller_user_id=None,
        )

    assert db.calls == []


@pytest.mark.asyncio
async def test_private_scope_filters_chunks_by_document_owner():
    db = CapturingDB()

    await RAGService.hybrid_search(
        db=db,
        organization_id=10,
        query_embedding=[0.0, 0.0],
        query_text="private document",
        knowledge_scope="private",
        caller_user_id=101,
    )

    assert len(db.calls) == 2
    for sql, params in db.calls:
        assert "JOIN documents d ON d.id = dc.document_id" in sql
        assert "d.owner = :caller_user_id" in sql
        assert "d.organization_id = :org_id" in sql
        assert params["org_id"] == 10
        assert params["caller_user_id"] == 101


@pytest.mark.asyncio
async def test_private_scope_cannot_become_cross_tenant_via_owner_parameter():
    db = CapturingDB()

    await RAGService.hybrid_search(
        db=db,
        organization_id=10,
        query_embedding=[0.0, 0.0],
        query_text="private document",
        knowledge_scope="private",
        caller_user_id=202,
    )

    for sql, params in db.calls:
        assert "d.organization_id = :org_id" in sql
        assert params["org_id"] == 10
        assert params["caller_user_id"] == 202


def test_private_scope_clause_remains_visibility_restricted():
    clause = RAGService._scope_clause("private")
    assert "dc.metadata" in clause
    assert "visibility" in clause
    assert "private" in clause
    assert "d.owner = :caller_user_id" in clause


def test_organization_scope_remains_organization_wide():
    clause = RAGService._scope_clause("organization")
    assert clause.strip() == ""
