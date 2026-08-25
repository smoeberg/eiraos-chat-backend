"""Add durable tenant-bound memory runtime.

Revision ID: 011_memory_runtime
Revises: 010_conversation_state
"""
from alembic import op
import sqlalchemy as sa


revision = "011_memory_runtime"
down_revision = "010_conversation_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_id", sa.String(64), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("memory_class", sa.String(32), nullable=False),
        sa.Column("scope_kind", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("provenance_json", sa.Text(), nullable=False),
        sa.Column("source_message_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=True),
        sa.Column("source_memory_item_id", sa.String(64), sa.ForeignKey("memory_records.item_id"), nullable=True),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("item_id", name="uq_memory_records_item_id"),
        sa.CheckConstraint("memory_class IN ('persistent_memory', 'user_org_knowledge')", name="ck_memory_records_durable_class"),
        sa.CheckConstraint("(scope_kind = 'user' AND owner_user_id IS NOT NULL) OR (scope_kind = 'organization' AND owner_user_id IS NULL)", name="ck_memory_records_scope_owner"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_memory_records_org"),
        sa.ForeignKeyConstraint(["actor_user_id", "organization_id"], ["organization_members.user_id", "organization_members.organization_id"], name="fk_memory_records_actor_member"),
        sa.ForeignKeyConstraint(["owner_user_id", "organization_id"], ["organization_members.user_id", "organization_members.organization_id"], name="fk_memory_records_owner_member"),
    )
    op.create_index("ix_memory_records_organization_id", "memory_records", ["organization_id"])
    op.create_index("ix_memory_records_owner_user_id", "memory_records", ["owner_user_id"])
    op.create_index("ix_memory_records_tenant_scope", "memory_records", ["organization_id", "scope_kind", "owner_user_id"])


def downgrade() -> None:
    op.drop_table("memory_records")