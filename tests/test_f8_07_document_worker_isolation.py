from pathlib import Path

from sqlalchemy import ForeignKeyConstraint

from eiraos.domains.documents.models import Document, DocumentChunk


ROOT = Path(__file__).parents[1]


def test_document_chunk_has_composite_tenant_foreign_key():
    constraints = [
        constraint
        for constraint in DocumentChunk.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    ]
    assert any(
        constraint.name == "fk_document_chunks_document_tenant"
        and tuple(column.name for column in constraint.columns)
        == ("document_id", "organization_id")
        for constraint in constraints
    )
    assert any(
        constraint.name == "uq_documents_id_organization"
        for constraint in Document.__table__.constraints
    )
    assert any(
        constraint.name == "fk_documents_organization"
        for constraint in Document.__table__.constraints
    )


def test_worker_queries_document_through_tenant_boundary_and_is_replay_safe():
    source = (ROOT / "src/eiraos/workers/tasks.py").read_text()
    client_source = (ROOT / "src/eiraos/workers/client.py").read_text()
    assert "Document.id == document_id" in source
    assert "Document.organization_id == organization_id" in source
    assert ".with_for_update()" in source
    assert 'if doc.status == "ready"' in source
    assert '_job_id=f"document-ingest:{organization_id}:{document_id}"' in client_source
