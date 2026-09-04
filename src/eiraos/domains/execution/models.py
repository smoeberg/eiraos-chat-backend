from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, JSON, String, Text, UniqueConstraint

from eiraos.core.database import Base


class ExecutionWorkflow(Base):
    __tablename__ = "execution_workflows"
    __table_args__ = (UniqueConstraint("organization_id", "workflow_id", name="uq_execution_workflow_org_id"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True)
    workflow_id = Column(String(128), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    state = Column(String(32), nullable=False, default="draft")
    stage = Column(String(64), nullable=False, default="Plan")
    progress = Column(Integer, nullable=False, default=0)
    next_action = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    version = Column(Integer, nullable=False, default=1)


class ExecutionGate(Base):
    __tablename__ = "execution_gates"
    __table_args__ = (UniqueConstraint("organization_id", "gate_id", name="uq_execution_gate_org_id"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True)
    gate_id = Column(String(128), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    detail = Column(Text, nullable=False, default="")
    required = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ExecutionDecision(Base):
    __tablename__ = "execution_decisions"
    __table_args__ = (UniqueConstraint("organization_id", "decision_id", name="uq_execution_decision_org_id"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True)
    decision_id = Column(String(128), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="open")
    owner = Column(String(255), nullable=False)
    age = Column(String(64), nullable=False, default="now")
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ExecutionProposal(Base):
    __tablename__ = "execution_proposals"
    __table_args__ = (UniqueConstraint("organization_id", "proposal_id", name="uq_execution_proposal_org_id"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True)
    proposal_id = Column(String(128), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    rationale = Column(Text, nullable=False)
    impact = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="proposed")
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ExecutionEventRecord(Base):
    __tablename__ = "execution_events"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True)
    event_type = Column(String(128), nullable=False, index=True)
    aggregate_id = Column(String(128), nullable=False, index=True)
    state = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    occurred_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
