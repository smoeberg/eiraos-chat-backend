"""Bind document chunks structurally to their document tenant.

Revision ID: 013_document_chunk_tenant_fk
Revises: 012_agent_audit
"""
from alembic import op
import sqlalchemy as sa


revision = "013_document_chunk_tenant_fk"
down_revision = "012_agent_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    orphan = connection.execute(sa.text(
        "SELECT 1 FROM documents d "
        "LEFT JOIN organizations o ON o.id = d.organization_id "
        "WHERE o.id IS NULL LIMIT 1"
    )).first()
    if orphan is not None:
        raise RuntimeError(
            "orphan document tenant detected; refusing structural migration"
        )
    mismatch = connection.execute(sa.text(
        "SELECT 1 FROM document_chunks c "
        "JOIN documents d ON d.id = c.document_id "
        "WHERE c.organization_id <> d.organization_id LIMIT 1"
    )).first()
    if mismatch is not None:
        raise RuntimeError(
            "document chunk tenant mismatch detected; refusing structural migration"
        )

    op.create_foreign_key(
        "fk_documents_organization",
        "documents",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_documents_id_organization", "documents", ["id", "organization_id"]
    )
    op.drop_constraint(
        "document_chunks_document_id_fkey", "document_chunks", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_document_chunks_document_tenant",
        "document_chunks",
        "documents",
        ["document_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_document_chunks_document_tenant", "document_chunks", type_="foreignkey"
    )
    op.create_foreign_key(
        "document_chunks_document_id_fkey",
        "document_chunks",
        "documents",
        ["document_id"],
        ["id"],
    )
    op.drop_constraint(
        "uq_documents_id_organization", "documents", type_="unique"
    )
    op.drop_constraint(
        "fk_documents_organization", "documents", type_="foreignkey"
    )
