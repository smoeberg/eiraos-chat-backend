import json

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from eiraos.application.agent_audit import (
    AgentAuditTrail,
    AgentAuditUnavailable,
    AgentEventType,
    SCHEMA_VERSION,
)
from eiraos.application.agent_loop import AgentRunLimits, LoopStep, run_agent_loop_async
from eiraos.application.execution_budget import ExecutionBudget
from eiraos.application.tool_authorization import AuthorizationDecision
from eiraos.core.database import Base
from eiraos.domains.identity.models import User
from eiraos.domains.organizations.models import Organization, OrganizationMember


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        db.add_all([
            User(id=1, email="audit@agent.test", username="agent-audit", role="member", is_enabled=True),
            Organization(id=1, name="agent-audit", slug="agent-audit"),
            OrganizationMember(user_id=1, organization_id=1, role="member"),
        ])
        await db.commit()
        yield db
    await engine.dispose()


@pytest.mark.asyncio
async def test_full_agent_path_is_durable_ordered_and_reconstructable(session):
    audit = AgentAuditTrail(
        session, run_id="run-1", organization_id=1, user_id=1,
        actor_context="user:1",
    )

    def planner(conversation, observation):
        return None if observation else LoopStep("lookup", "knowledge.read", {"secret": "not logged"})

    async def execute(step):
        return {"answer": "sensitive result"}

    outcome = await run_agent_loop_async(
        planner,
        lambda step: AuthorizationDecision(True, "AUTHORIZED"),
        ExecutionBudget(2, 10), execute, "conversation",
        limits=AgentRunLimits(2, 2, 1), audit=audit,
    )
    assert outcome.status == "COMPLETE"
    events = await audit.read_run()
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert [event.event_type for event in events] == [
        "run.started", "planner.decision", "tool.selected",
        "authorization.decision", "budget.decision", "tool.execution.started",
        "tool.execution.completed", "observation.received",
        "planner.decision", "run.terminated",
    ]
    assert all(event.schema_version == SCHEMA_VERSION for event in events)
    encoded = " ".join(event.payload_json for event in events)
    assert "not logged" not in encoded and "sensitive result" not in encoded
    assert events[-1].outcome == "COMPLETE"


@pytest.mark.asyncio
async def test_writer_redacts_sensitive_keys_before_persistence(session):
    audit = AgentAuditTrail(session, run_id="run-redact", organization_id=1, user_id=1, actor_context="user:1")
    await audit.record(AgentEventType.TOOL_SELECTED, payload={
        "tool": "safe", "arguments": {"token": "abc"},
        "nested": {"password": "secret", "value": "visible"},
    })
    payload = json.loads((await audit.read_run())[0].payload_json)
    assert payload["arguments"] == "[REDACTED]"
    assert payload["nested"]["password"] == "[REDACTED]"
    assert payload["nested"]["value"] == "visible"


@pytest.mark.asyncio
async def test_required_audit_failure_stops_before_planning_or_execution():
    calls = []

    class FailedAudit:
        async def record(self, *args, **kwargs):
            raise AgentAuditUnavailable("unavailable")

    async def execute(step):
        calls.append("execute")

    with pytest.raises(AgentAuditUnavailable):
        await run_agent_loop_async(
            lambda conversation, observation: calls.append("plan"),
            lambda step: AuthorizationDecision(True, "AUTHORIZED"),
            ExecutionBudget(1, 10), execute, "conversation",
            limits=AgentRunLimits(1, 1, 1), audit=FailedAudit(),
        )
    assert calls == []


@pytest.mark.asyncio
async def test_tool_failure_is_terminal_without_exception_or_secret_result(session):
    audit = AgentAuditTrail(session, run_id="run-fail", organization_id=1, user_id=1, actor_context="user:1")

    async def execute(step):
        raise RuntimeError("credential=secret")

    outcome = await run_agent_loop_async(
        lambda conversation, observation: LoopStep("broken", "write", {}),
        lambda step: AuthorizationDecision(True, "AUTHORIZED"),
        ExecutionBudget(1, 10), execute, "conversation",
        limits=AgentRunLimits(1, 1, 1), audit=audit,
    )
    assert outcome.status == "FAILED" and outcome.reason_code == "TOOL_FAILED"
    events = await audit.read_run()
    assert events[-2].event_type == "tool.execution.failed"
    assert events[-1].event_type == "run.terminated"
    assert "credential=secret" not in " ".join(event.payload_json for event in events)


@pytest.mark.asyncio
async def test_untrusted_tool_identity_is_fingerprinted_not_logged(session):
    audit = AgentAuditTrail(session, run_id="run-identity", organization_id=1, user_id=1, actor_context="user:1")

    async def execute(step):
        return None

    outcome = await run_agent_loop_async(
        lambda conversation, observation: LoopStep("token sk-live-secret", "bad capability", {}),
        lambda step: AuthorizationDecision(False, "CAPABILITY_NOT_AUTHORIZED"),
        ExecutionBudget(1, 10), execute, "conversation",
        limits=AgentRunLimits(1, 1, 1), audit=audit,
    )
    assert outcome.status == "DENIED"
    encoded = " ".join(event.payload_json for event in await audit.read_run())
    assert "sk-live-secret" not in encoded and "bad capability" not in encoded
    assert "tool:sha256:" in encoded and "capability:sha256:" in encoded


@pytest.mark.asyncio
async def test_untrusted_reason_code_is_not_returned_or_persisted(session):
    audit = AgentAuditTrail(session, run_id="run-reason", organization_id=1, user_id=1, actor_context="user:1")

    async def execute(step):
        return None

    outcome = await run_agent_loop_async(
        lambda conversation, observation: LoopStep("safe", "read", {}),
        lambda step: AuthorizationDecision(False, "token sk-live-secret"),
        ExecutionBudget(1, 10), execute, "conversation",
        limits=AgentRunLimits(1, 1, 1), audit=audit,
    )
    assert outcome.reason_code == "UNSAFE_REASON_CODE"
    encoded = " ".join(
        f"{event.reason_code} {event.payload_json}" for event in await audit.read_run()
    )
    assert "sk-live-secret" not in encoded


def test_agent_audit_migration_is_single_head():
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    assert scripts.get_heads() == ["013_document_chunk_tenant_fk"]
