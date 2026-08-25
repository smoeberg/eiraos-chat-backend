"""Add durable agent audit event ledger.

Revision ID: 012_agent_audit
Revises: 011_memory_runtime
"""
from alembic import op
import sqlalchemy as sa


revision = "012_agent_audit"
down_revision = "011_memory_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("actor_context", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("outcome", sa.String(64), nullable=True),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("event_id", name="uq_agent_audit_events_event_id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_audit_events_run_sequence"),
        sa.CheckConstraint("sequence > 0", name="ck_agent_audit_events_sequence_positive"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_agent_audit_events_org"),
        sa.ForeignKeyConstraint(["user_id", "organization_id"], ["organization_members.user_id", "organization_members.organization_id"], name="fk_agent_audit_events_member"),
    )
    op.create_index("ix_agent_audit_events_run_id", "agent_audit_events", ["run_id"])
    op.create_index("ix_agent_audit_events_organization_id", "agent_audit_events", ["organization_id"])
    op.create_index("ix_agent_audit_events_user_id", "agent_audit_events", ["user_id"])
    op.create_index("ix_agent_audit_events_tenant_run", "agent_audit_events", ["organization_id", "run_id", "sequence"])


def downgrade() -> None:
    op.drop_table("agent_audit_events")