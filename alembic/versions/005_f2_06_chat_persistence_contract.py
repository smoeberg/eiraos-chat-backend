"""Create the F2-06 chat execution ledger and message bindings.

Revision ID: 005_chat_persistence
Revises: 004_provider_usage
"""
from alembic import op
import sqlalchemy as sa


revision = "005_chat_persistence"
down_revision = "004_provider_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_executions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("execution_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("bot_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_record_id", sa.Integer(), nullable=True),
        sa.Column("user_message_id", sa.Integer(), nullable=True),
        sa.Column("assistant_message_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="prepared"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["idempotency_record_id"], ["idempotency_records.id"]),
        sa.ForeignKeyConstraint(["user_message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["assistant_message_id"], ["messages.id"]),
        sa.UniqueConstraint("execution_id", name="uq_chat_executions_execution_id"),
        sa.UniqueConstraint("idempotency_record_id", name="uq_chat_executions_idempotency_record_id"),
        sa.UniqueConstraint("user_message_id", name="uq_chat_executions_user_message_id"),
        sa.UniqueConstraint("assistant_message_id", name="uq_chat_executions_assistant_message_id"),
    )
    for column in ("execution_id", "request_id", "conversation_id", "organization_id", "user_id", "bot_id"):
        op.create_index(f"ix_chat_executions_{column}", "chat_executions", [column])
    op.create_index(
        "ix_chat_executions_tenant_conversation", "chat_executions",
        ["organization_id", "conversation_id"],
    )
    op.add_column("messages", sa.Column("execution_id", sa.String(length=64), nullable=True))
    op.create_index("ix_messages_execution_id", "messages", ["execution_id"])
    op.create_foreign_key(
        "fk_messages_execution", "messages", "chat_executions",
        ["execution_id"], ["execution_id"],
    )
    op.create_unique_constraint(
        "uq_messages_execution_role", "messages", ["execution_id", "role"],
    )
    op.add_column("provider_usage_records", sa.Column("chat_execution_id", sa.Integer(), nullable=True))
    op.create_index("ix_provider_usage_records_chat_execution_id", "provider_usage_records", ["chat_execution_id"])
    op.create_foreign_key(
        "fk_provider_usage_chat_execution", "provider_usage_records", "chat_executions",
        ["chat_execution_id"], ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_provider_usage_chat_execution", "provider_usage_records", type_="foreignkey")
    op.drop_index("ix_provider_usage_records_chat_execution_id", table_name="provider_usage_records")
    op.drop_column("provider_usage_records", "chat_execution_id")
    op.drop_constraint("uq_messages_execution_role", "messages", type_="unique")
    op.drop_constraint("fk_messages_execution", "messages", type_="foreignkey")
    op.drop_index("ix_messages_execution_id", table_name="messages")
    op.drop_column("messages", "execution_id")
    op.drop_table("chat_executions")
