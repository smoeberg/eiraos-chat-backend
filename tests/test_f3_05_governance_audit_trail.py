import inspect

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from eiraos.api.v1 import chat
from eiraos.application.authorization import AuthorizationContext
from eiraos.application.chat_persistence import ChatPersistenceContract, PersistenceConflict
from eiraos.application.governance_audit import (
    GovernanceAuditTrail,
    GovernanceAuditUnavailable,
    permit_fingerprint,
    request_fingerprint,
)
from eiraos.application.provider_execution_policy import authorize_provider_execution
from eiraos.core.database import Base
from eiraos.domains.agents.models import Bot
from eiraos.domains.conversations.models import ChatExecution
from eiraos.domains.governance.capabilities import (
    Capability,
    Principal,
    PrincipalType,
    decide_role_capability,
)
from eiraos.domains.governance.models import GovernanceDecisionRecord


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


def _authorization() -> AuthorizationContext:
    decision = decide_role_capability(
        role="member",
        capability=Capability.CONVERSATION_CREATE,
        principal_organization_id=1,
        resource_organization_id=1,
    )
    return AuthorizationContext(
        user=Principal(PrincipalType.USER, "2", 1),
        organization=Principal(PrincipalType.ORGANIZATION, "1", 1),
        role="member",
        decision=decision,
    )


def _bot() -> Bot:
    return Bot(
        id=4,
        organization_id=1,
        title="bot",
        provider="openai",
        model="gpt-4o",
        tool_scope="standard",
        credential_scope="organization",
        bot_visibility="private",
        is_public=False,
    )


async def _allowed_decision(session) -> tuple[str, object]:
    permit = authorize_provider_execution(
        authorization=_authorization(), bot=_bot(), caller_organization_id=1,
    )
    decision_id = await GovernanceAuditTrail(session).record_provider_decision(
        request_id="request-1",
        request_hash=request_fingerprint(b'{"prompt":"secret"}'),
        authorization=_authorization(),
        bot_id=4,
        bot_organization_id=1,
        allowed=True,
        reason="granted",
        provider=permit.provider,
        model=permit.model,
        permit=permit,
    )
    return decision_id, permit


@pytest.mark.asyncio
async def test_allowed_decision_is_non_secret_and_content_bound(session):
    decision_id, permit = await _allowed_decision(session)
    record = (await session.execute(select(GovernanceDecisionRecord))).scalar_one()
    assert record.decision_id == decision_id
    assert record.request_hash == request_fingerprint(b'{"prompt":"secret"}')
    assert "secret" not in repr(record.__dict__)
    assert record.permit_fingerprint == permit_fingerprint(permit)
    assert record.allowed and record.finalized_at is None


@pytest.mark.asyncio
async def test_denied_decision_is_immediately_terminal(session):
    decision_id = await GovernanceAuditTrail(session).record_provider_decision(
        request_id="request-denied",
        request_hash=request_fingerprint(b"denied"),
        authorization=_authorization(),
        bot_id=4,
        bot_organization_id=1,
        allowed=False,
        reason="provider_capability_denied",
        provider="openai",
        model="gpt-4o",
        permit=None,
    )
    record = (
        await session.execute(
            select(GovernanceDecisionRecord).where(GovernanceDecisionRecord.decision_id == decision_id)
        )
    ).scalar_one()
    assert (record.result_status, record.response_status) == ("denied", 403)
    assert record.finalized_at is not None and record.execution_id is None


@pytest.mark.asyncio
async def test_decision_binds_to_execution_and_result_atomically(session):
    decision_id, _ = await _allowed_decision(session)
    persistence = ChatPersistenceContract(session)
    persisted = await persistence.prepare_exchange(
        execution_id="execution-1",
        request_id="request-1",
        conversation_id=3,
        organization_id=1,
        user_id=2,
        bot_id=4,
        bot_organization_id=1,
        provider="openai",
        model="gpt-4o",
        prompt="secret prompt",
        idempotency_record_id=None,
        estimated_tokens=1,
        estimated_cost=1,
        verification=False,
        governance_decision_id=decision_id,
    )
    record = (await session.execute(select(GovernanceDecisionRecord))).scalar_one()
    execution = (await session.execute(select(ChatExecution))).scalar_one()
    assert record.execution_id == persisted.execution_id
    assert execution.governance_audit_required

    assert await persistence.finalize(
        execution_id=persisted.execution_id,
        terminal_status="completed",
        content="answer",
        response_status=200,
        response_reference="answer",
        lease_token=None,
    )
    record = (await session.execute(select(GovernanceDecisionRecord))).scalar_one()
    assert (record.result_status, record.response_status) == ("completed", 200)
    assert record.finalized_at is not None


@pytest.mark.asyncio
async def test_execution_rejects_missing_decision_binding(session):
    with pytest.raises(PersistenceConflict, match="governance decision"):
        await ChatPersistenceContract(session).prepare_exchange(
            execution_id="execution-invalid",
            request_id="request",
            conversation_id=3,
            organization_id=1,
            user_id=2,
            bot_id=4,
            bot_organization_id=1,
            provider="openai",
            model="gpt-4o",
            prompt="prompt",
            idempotency_record_id=None,
            estimated_tokens=1,
            estimated_cost=1,
            verification=False,
            governance_decision_id="missing",
        )


@pytest.mark.asyncio
async def test_audit_write_failure_is_fail_closed(monkeypatch, session):
    async def fail_commit():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(session, "commit", fail_commit)
    with pytest.raises(GovernanceAuditUnavailable):
        await GovernanceAuditTrail(session).record_provider_decision(
            request_id="request",
            request_hash=request_fingerprint(b"request"),
            authorization=_authorization(),
            bot_id=4,
            bot_organization_id=1,
            allowed=True,
            reason="granted",
            provider="openai",
            model="gpt-4o",
            permit=authorize_provider_execution(
                authorization=_authorization(), bot=_bot(), caller_organization_id=1,
            ),
        )


def test_policy_decision_is_persisted_before_idempotency_and_provider():
    source = inspect.getsource(chat.create_chat_completion)
    decision = source.index("record_provider_decision(")
    assert decision < source.index("begin_idempotency")
    assert decision < source.index("_provider_for_bot(")


def test_f3_05_is_single_migration_head():
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["013_document_chunk_tenant_fk"]
    revision = script.get_revision("008_governance_audit")
    assert revision is not None and revision.down_revision == "007_tenant_isolation"


def test_audit_identity_and_execution_are_structurally_tenant_bound():
    names = {
        constraint.name
        for constraint in GovernanceDecisionRecord.__table__.foreign_key_constraints
    }
    assert {
        "fk_governance_decision_org",
        "fk_governance_decision_member",
        "fk_governance_decision_resource_org",
        "fk_governance_decision_tenant_execution",
    } <= names
