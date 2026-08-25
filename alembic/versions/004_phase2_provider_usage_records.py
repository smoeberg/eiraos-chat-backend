"""Create durable provider usage accounting records.

Revision ID: 004_provider_usage
Revises: 003_idempotency_lease_token
"""

from alembic import op
import sqlalchemy as sa


revision = "004_provider_usage"
down_revision = "003_idempotency_lease_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_usage_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("execution_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Numeric(20, 10), nullable=False, server_default="0"),
        sa.Column("actual_cost", sa.Numeric(20, 10), nullable=True),
        sa.Column("verification", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_provider_usage_records_request_id", "provider_usage_records", ["request_id"])
    op.create_index("ix_provider_usage_records_execution_id", "provider_usage_records", ["execution_id"])
    op.create_index("ix_provider_usage_records_user_id", "provider_usage_records", ["user_id"])
    op.create_index("ix_provider_usage_records_organization_id", "provider_usage_records", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_provider_usage_records_organization_id", table_name="provider_usage_records")
    op.drop_index("ix_provider_usage_records_user_id", table_name="provider_usage_records")
    op.drop_index("ix_provider_usage_records_execution_id", table_name="provider_usage_records")
    op.drop_index("ix_provider_usage_records_request_id", table_name="provider_usage_records")
    op.drop_table("provider_usage_records")
