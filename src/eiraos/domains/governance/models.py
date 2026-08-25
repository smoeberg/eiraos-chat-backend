from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKeyConstraint, Index, Integer, String, Text, text

from eiraos.core.database import Base


class GovernanceDecisionRecord(Base):
    """Durable, non-secret evidence for one governance decision."""

    __tablename__ = "governance_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"],
            name="fk_governance_decision_org",
        ),
        ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["organization_members.user_id", "organization_members.organization_id"],
            name="fk_governance_decision_member",
        ),
        ForeignKeyConstraint(
            ["resource_organization_id"], ["organizations.id"],
            name="fk_governance_decision_resource_org",
        ),
        ForeignKeyConstraint(
            ["execution_id", "organization_id"],
            ["chat_executions.execution_id", "chat_executions.organization_id"],
            name="fk_governance_decision_tenant_execution",
        ),
        Index("ix_governance_decisions_tenant_request", "organization_id", "request_id"),
        Index("ix_governance_decisions_tenant_execution", "organization_id", "execution_id"),
    )

    id = Column(Integer, primary_key=True)
    decision_id = Column(String(64), nullable=False, unique=True, index=True)
    request_id = Column(String(128), nullable=False, index=True)
    request_hash = Column(String(64), nullable=False)
    organization_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    role = Column(String(50), nullable=False)
    policy = Column(String(100), nullable=False)
    policy_version = Column(String(32), nullable=False)
    capability = Column(String(100), nullable=False)
    allowed = Column(Boolean, nullable=False)
    reason = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(String(128), nullable=False)
    resource_organization_id = Column(Integer, nullable=False)
    provider = Column(String(64), nullable=True)
    model = Column(String(128), nullable=True)
    permit_fingerprint = Column(String(64), nullable=True)
    execution_id = Column(String(64), nullable=True, index=True)
    result_status = Column(String(32), nullable=True)
    response_status = Column(Integer, nullable=True)
    failure_code = Column(String(32), nullable=True)
    decided_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))
    finalized_at = Column(DateTime, nullable=True)
