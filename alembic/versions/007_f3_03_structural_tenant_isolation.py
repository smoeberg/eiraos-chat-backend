"""Add structural tenant isolation across chat resources.

Revision ID: 007_tenant_isolation
Revises: 006_failure_recovery
"""
from alembic import op
import sqlalchemy as sa


revision = "007_tenant_isolation"
down_revision = "006_failure_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Referenced column sets must be unique before composite tenant FKs exist.
    op.create_unique_constraint(
        "uq_org_members_user_org", "organization_members", ["user_id", "organization_id"],
    )
    op.create_unique_constraint("uq_conversations_id_org", "conversations", ["id", "organization_id"])
    op.create_unique_constraint("uq_bots_id_org", "bots", ["id", "organization_id"])
    op.create_unique_constraint(
        "uq_idempotency_id_org_user", "idempotency_records", ["id", "organization_id", "user_id"],
    )

    # Public bots may be owned by another tenant. Preserve that provenance
    # explicitly instead of pretending the bot belongs to the execution tenant.
    op.add_column("chat_executions", sa.Column("bot_organization_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE chat_executions AS e SET bot_organization_id = b.organization_id "
        "FROM bots AS b WHERE b.id = e.bot_id"
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM chat_executions WHERE bot_organization_id IS NULL) "
        "THEN RAISE EXCEPTION 'F3-03: orphan chat execution bot'; END IF; END $$"
    )
    op.alter_column("chat_executions", "bot_organization_id", nullable=False)
    op.create_index(
        "ix_chat_executions_bot_organization_id", "chat_executions", ["bot_organization_id"],
    )

    op.add_column("messages", sa.Column("organization_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE messages AS m SET organization_id = c.organization_id "
        "FROM conversations AS c WHERE c.id = m.conversation_id"
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM messages WHERE organization_id IS NULL) "
        "THEN RAISE EXCEPTION 'F3-03: orphan message conversation'; END IF; END $$"
    )
    op.alter_column("messages", "organization_id", nullable=False)
    op.create_index("ix_messages_organization_id", "messages", ["organization_id"])

    op.create_unique_constraint(
        "uq_chat_executions_execution_org", "chat_executions", ["execution_id", "organization_id"],
    )
    op.create_unique_constraint(
        "uq_chat_executions_id_org", "chat_executions", ["id", "organization_id"],
    )

    op.create_foreign_key(
        "fk_bots_org", "bots", "organizations", ["organization_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_conversations_org", "conversations", "organizations", ["organization_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_conversations_member", "conversations", "organization_members",
        ["user_id", "organization_id"], ["user_id", "organization_id"],
    )
    op.create_foreign_key(
        "fk_chat_executions_org", "chat_executions", "organizations", ["organization_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_chat_executions_tenant_conversation", "chat_executions", "conversations",
        ["conversation_id", "organization_id"], ["id", "organization_id"],
    )
    op.create_foreign_key(
        "fk_chat_executions_member", "chat_executions", "organization_members",
        ["user_id", "organization_id"], ["user_id", "organization_id"],
    )
    op.create_foreign_key(
        "fk_chat_executions_bot_owner", "chat_executions", "bots",
        ["bot_id", "bot_organization_id"], ["id", "organization_id"],
    )
    op.create_foreign_key(
        "fk_chat_executions_tenant_idempotency", "chat_executions", "idempotency_records",
        ["idempotency_record_id", "organization_id", "user_id"],
        ["id", "organization_id", "user_id"],
    )
    op.create_foreign_key(
        "fk_messages_tenant_conversation", "messages", "conversations",
        ["conversation_id", "organization_id"], ["id", "organization_id"],
    )
    op.create_foreign_key(
        "fk_messages_tenant_execution", "messages", "chat_executions",
        ["execution_id", "organization_id"], ["execution_id", "organization_id"],
    )
    op.create_foreign_key(
        "fk_provider_usage_tenant_execution", "provider_usage_records", "chat_executions",
        ["chat_execution_id", "organization_id"], ["id", "organization_id"],
    )


def downgrade() -> None:
    for table, constraint in (
        ("provider_usage_records", "fk_provider_usage_tenant_execution"),
        ("messages", "fk_messages_tenant_execution"),
        ("messages", "fk_messages_tenant_conversation"),
        ("chat_executions", "fk_chat_executions_tenant_idempotency"),
        ("chat_executions", "fk_chat_executions_bot_owner"),
        ("chat_executions", "fk_chat_executions_member"),
        ("chat_executions", "fk_chat_executions_tenant_conversation"),
        ("chat_executions", "fk_chat_executions_org"),
        ("conversations", "fk_conversations_member"),
        ("conversations", "fk_conversations_org"),
        ("bots", "fk_bots_org"),
    ):
        op.drop_constraint(constraint, table, type_="foreignkey")

    op.drop_constraint("uq_chat_executions_id_org", "chat_executions", type_="unique")
    op.drop_constraint("uq_chat_executions_execution_org", "chat_executions", type_="unique")
    op.drop_index("ix_messages_organization_id", table_name="messages")
    op.drop_column("messages", "organization_id")
    op.drop_index("ix_chat_executions_bot_organization_id", table_name="chat_executions")
    op.drop_column("chat_executions", "bot_organization_id")
    op.drop_constraint("uq_idempotency_id_org_user", "idempotency_records", type_="unique")
    op.drop_constraint("uq_bots_id_org", "bots", type_="unique")
    op.drop_constraint("uq_conversations_id_org", "conversations", type_="unique")
    op.drop_constraint("uq_org_members_user_org", "organization_members", type_="unique")
