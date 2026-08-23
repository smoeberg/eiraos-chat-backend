"""Add lease_until to idempotency_records

Revision ID: 002_idempotency_lease
Revises: 001_authority_token_version_idempotency
Create Date: 2026-08-23
"""
from alembic import op
import sqlalchemy as sa

revision = "002_idempotency_lease"
down_revision = "001_authority_token_version_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "idempotency_records",
        sa.Column("lease_until", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("idempotency_records", "lease_until")
