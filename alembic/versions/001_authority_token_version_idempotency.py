"""Add token_version to users and create idempotency_records.

Revision ID: 0019
Revises:
Create Date: 2026-08-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # token_version on users (idempotent)
    insp = sa.inspect(bind)
    if "users" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("users")]
        if "token_version" not in cols:
            op.add_column(
                "users",
                sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"),
            )

    # idempotency_records table
    if "idempotency_records" not in insp.get_table_names():
        op.create_table(
            "idempotency_records",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("organization_id", sa.Integer(), nullable=False, index=True),
            sa.Column("user_id", sa.Integer(), nullable=False, index=True),
            sa.Column("key", sa.String(128), nullable=False),
            sa.Column("request_hash", sa.String(64), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="processing"),
            sa.Column("response_status", sa.Integer(), nullable=True),
            sa.Column("response_reference", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("organization_id", "user_id", "key",
                                name="uq_idempotency_org_user_key"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "idempotency_records" in insp.get_table_names():
        op.drop_table("idempotency_records")
    if "users" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("users")]
        if "token_version" in cols:
            op.drop_column("users", "token_version")
