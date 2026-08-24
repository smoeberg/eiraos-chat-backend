"""Tests for RAG knowledge scope and private/organization document isolation."""
import pytest
from eiraos.domains.documents.rag_service import RAGService

def test_scope_clause_private_behavior():
    """Verify private scope clause in RAGService checks visibility=private without user ID filter."""
    clause = RAGService._scope_clause("private")
    assert "visibility" in clause
    assert "private" in clause
    # Confirm it does NOT filter by user/owner in current implementation
    assert "owner" not in clause
    assert "user_id" not in clause

def test_scope_clause_organization_behavior():
    """Verify organization scope clause returns organization-wide chunks."""
    clause = RAGService._scope_clause("organization")
    assert clause.strip() == ""
