"""Add bounded retry and failure recovery metadata.

Revision ID: 006_failure_recovery
Revises: 005_chat_persistence
"""
from alembic import op
import sqlalchemy as sa


revision = "006_failure_recovery"
down_revision = "005_chat_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "chat_executions_idempotency_record_id_fkey",
        "chat_executions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_chat_executions_idempotency_record",
        "chat_executions",
        "idempotency_records",
        ["idempotency_record_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "chat_executions",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "chat_executions",
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "chat_executions",
        sa.Column("last_failure_code", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "chat_executions",
        sa.Column("failure_retryable", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "chat_executions",
        sa.Column("partial_response", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "chat_executions",
        sa.Column("recovered_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_chat_executions_status", "chat_executions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_chat_executions_status", table_name="chat_executions")
    for column in (
        "recovered_at",
        "partial_response",
        "failure_retryable",
        "last_failure_code",
        "max_attempts",
        "attempt_count",
    ):
        op.drop_column("chat_executions", column)
    op.drop_constraint(
        "fk_chat_executions_idempotency_record",
        "chat_executions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "chat_executions_idempotency_record_id_fkey",
        "chat_executions",
        "idempotency_records",
        ["idempotency_record_id"],
        ["id"],
    )
