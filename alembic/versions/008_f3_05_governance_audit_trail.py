"""Create durable governance decision evidence.

Revision ID: 008_governance_audit
Revises: 007_tenant_isolation
"""
from alembic import op
import sqlalchemy as sa


revision = "008_governance_audit"
down_revision = "007_tenant_isolation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "governance_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.String(64), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("policy", sa.String(100), nullable=False),
        sa.Column("policy_version", sa.String(32), nullable=False),
        sa.Column("capability", sa.String(100), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("resource_organization_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("permit_fingerprint", sa.String(64), nullable=True),
        sa.Column("execution_id", sa.String(64), nullable=True),
        sa.Column("result_status", sa.String(32), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("failure_code", sa.String(32), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("decision_id", name="uq_governance_decisions_decision_id"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"],
            name="fk_governance_decision_org",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["organization_members.user_id", "organization_members.organization_id"],
            name="fk_governance_decision_member",
        ),
        sa.ForeignKeyConstraint(
            ["resource_organization_id"], ["organizations.id"],
            name="fk_governance_decision_resource_org",
        ),
        sa.ForeignKeyConstraint(
            ["execution_id", "organization_id"],
            ["chat_executions.execution_id", "chat_executions.organization_id"],
            name="fk_governance_decision_tenant_execution",
        ),
    )
    for column in ("decision_id", "request_id", "organization_id", "user_id", "execution_id"):
        op.create_index(f"ix_governance_decisions_{column}", "governance_decisions", [column])
    op.create_index(
        "ix_governance_decisions_tenant_request", "governance_decisions",
        ["organization_id", "request_id"],
    )
    op.create_index(
        "ix_governance_decisions_tenant_execution", "governance_decisions",
        ["organization_id", "execution_id"],
    )
    op.add_column(
        "chat_executions",
        sa.Column("governance_audit_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("chat_executions", "governance_audit_required")
    op.drop_table("governance_decisions")
