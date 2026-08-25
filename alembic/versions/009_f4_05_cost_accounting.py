"""Add execution-linked provider cost ledger metadata.

Revision ID: 009_cost_accounting
Revises: 008_governance_audit
"""
from alembic import op
import sqlalchemy as sa


revision = "009_cost_accounting"
down_revision = "008_governance_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("provider_usage_records", sa.Column(
        "operation", sa.String(32), nullable=False, server_default="reservation",
    ))
    op.add_column("provider_usage_records", sa.Column(
        "attempt", sa.Integer(), nullable=False, server_default="1",
    ))
    op.add_column("provider_usage_records", sa.Column(
        "usage_source", sa.String(32), nullable=False, server_default="reservation",
    ))
    op.add_column("provider_usage_records", sa.Column("pricing_revision", sa.String(32), nullable=True))
    op.create_unique_constraint(
        "uq_provider_usage_execution_attempt_operation_source",
        "provider_usage_records",
        ["chat_execution_id", "attempt", "operation", "usage_source"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_provider_usage_execution_attempt_operation_source",
        "provider_usage_records",
        type_="unique",
    )
    op.drop_column("provider_usage_records", "pricing_revision")
    op.drop_column("provider_usage_records", "usage_source")
    op.drop_column("provider_usage_records", "attempt")
    op.drop_column("provider_usage_records", "operation")
