"""Add durable conversation lifecycle and optimistic version.

Revision ID: 010_conversation_state
Revises: 009_cost_accounting
"""
from alembic import op
import sqlalchemy as sa


revision = "010_conversation_state"
down_revision = "009_cost_accounting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column(
        "lifecycle", sa.String(16), nullable=False, server_default="active",
    ))
    op.add_column("conversations", sa.Column(
        "version", sa.Integer(), nullable=False, server_default="1",
    ))
    op.add_column("conversations", sa.Column("archived_at", sa.DateTime(), nullable=True))
    op.create_check_constraint(
        "ck_conversations_lifecycle", "conversations",
        "lifecycle IN ('active', 'archived')",
    )
    op.create_check_constraint("ck_conversations_version_positive", "conversations", "version > 0")
    op.create_check_constraint(
        "ck_conversations_archive_state", "conversations",
        "(lifecycle = 'active' AND archived_at IS NULL) OR "
        "(lifecycle = 'archived' AND archived_at IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_conversations_archive_state", "conversations", type_="check")
    op.drop_constraint("ck_conversations_version_positive", "conversations", type_="check")
    op.drop_constraint("ck_conversations_lifecycle", "conversations", type_="check")
    op.drop_column("conversations", "archived_at")
    op.drop_column("conversations", "version")
    op.drop_column("conversations", "lifecycle")
