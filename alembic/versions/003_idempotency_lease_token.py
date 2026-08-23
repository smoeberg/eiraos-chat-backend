"""Add lease_token fencing + expires_at index

Revision ID: 003_idempotency_lease_token
Revises: 002_idempotency_lease
Create Date: 2026-08-23
"""
from alembic import op
import sqlalchemy as sa

revision = "003_idempotency_lease_token"
down_revision = "002_idempotency_lease"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "idempotency_records",
        sa.Column("lease_token", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_idempotency_expires_at",
        "idempotency_records",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_idempotency_expires_at", table_name="idempotency_records")
    op.drop_column("idempotency_records", "lease_token")
