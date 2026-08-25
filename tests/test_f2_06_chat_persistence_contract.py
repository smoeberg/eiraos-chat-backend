from datetime import datetime, timedelta, timezone

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from eiraos.application.chat_persistence import (
    ChatPersistenceContract,
    PersistenceConflict,
    execution_identity,
)
from eiraos.core.database import Base
from eiraos.domains.conversations.models import ChatExecution, Message
from eiraos.domains.idempotency.models import IdempotencyRecord
from eiraos.domains.usage.models import ProviderUsageRecord


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


def test_execution_identity_is_replay_stable_and_tenant_bound():
    first = execution_identity(
        organization_id=1, user_id=2, idempotency_key="same", idempotency_record_id=7,
    )
    assert first == execution_identity(
        organization_id=1, user_id=2, idempotency_key="same", idempotency_record_id=7,
    )
    assert first != execution_identity(organization_id=9, user_id=2, idempotency_key="same")
    assert first != execution_identity(
        organization_id=1, user_id=2, idempotency_key="same", idempotency_record_id=8,
    )
    assert execution_identity(organization_id=1, user_id=2, idempotency_key=None) != execution_identity(
        organization_id=1, user_id=2, idempotency_key=None,
    )


@pytest.mark.asyncio
async def test_prepare_atomically_binds_execution_messages_usage_and_idempotency(session):
    idem = IdempotencyRecord(
        organization_id=1, user_id=2, key="key", request_hash="a" * 64,
        status="processing", lease_token="lease",
        lease_until=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    session.add(idem)
    await session.commit()
    contract = ChatPersistenceContract(session)
    persisted = await contract.prepare_exchange(
        execution_id="execution-1", request_id="request-1", conversation_id=3,
        organization_id=1, user_id=2, bot_id=4, bot_organization_id=1,
        provider="openai", model="model",
        prompt="hello", idempotency_record_id=idem.id, estimated_tokens=42,
        estimated_cost=42.0, verification=False,
    )

    execution = (await session.execute(select(ChatExecution))).scalar_one()
    messages = (await session.execute(select(Message).order_by(Message.id))).scalars().all()
    usage = (await session.execute(select(ProviderUsageRecord))).scalar_one()
    assert persisted.execution_id == execution.execution_id == usage.execution_id
    assert usage.chat_execution_id == execution.id
    assert execution.bot_organization_id == 1
    assert [message.role for message in messages] == ["user", "assistant"]
    assert {message.execution_id for message in messages} == {execution.execution_id}
    assert {message.organization_id for message in messages} == {execution.organization_id}
    assert execution.user_message_id == messages[0].id
    assert execution.assistant_message_id == messages[1].id
    assert usage.total_tokens == 42


@pytest.mark.asyncio
async def test_finalize_updates_assistant_execution_and_idempotency_in_one_contract(session):
    idem = IdempotencyRecord(
        organization_id=1, user_id=2, key="key", request_hash="b" * 64,
        status="processing", lease_token="lease",
        lease_until=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    session.add(idem)
    await session.commit()
    contract = ChatPersistenceContract(session)
    persisted = await contract.prepare_exchange(
        execution_id="execution-2", request_id="request-2", conversation_id=3,
        organization_id=1, user_id=2, bot_id=4, bot_organization_id=1,
        provider="openai", model="model",
        prompt="hello", idempotency_record_id=idem.id, estimated_tokens=10,
        estimated_cost=10.0, verification=False,
    )
    assert await contract.mark_streaming(persisted.execution_id)
    assert await contract.finalize(
        execution_id=persisted.execution_id, terminal_status="completed", content="answer",
        response_status=200, response_reference='{"content":"answer"}', lease_token="lease",
    )

    execution = (await session.execute(select(ChatExecution))).scalar_one()
    assistant = (await session.execute(select(Message).where(Message.role == "assistant"))).scalar_one()
    refreshed_idem = (await session.execute(select(IdempotencyRecord))).scalar_one()
    assert (execution.status, assistant.status, assistant.content) == ("completed", "completed", "answer")
    assert refreshed_idem.status == "completed"
    assert refreshed_idem.response_reference == '{"content":"answer"}'

    assert not await contract.finalize(
        execution_id=persisted.execution_id, terminal_status="failed", content="overwritten",
        response_status=500, response_reference="failed", lease_token="lease",
    )
    assert (await session.execute(select(func.count(Message.id)).where(
        Message.execution_id == persisted.execution_id,
        Message.role == "assistant",
    ))).scalar_one() == 1
    assert (await session.execute(select(Message).where(Message.role == "assistant"))).scalar_one().content == "answer"


@pytest.mark.asyncio
async def test_wrong_lease_fails_closed_before_any_terminal_mutation(session):
    idem = IdempotencyRecord(
        organization_id=1, user_id=2, key="key", request_hash="c" * 64,
        status="processing", lease_token="owner",
        lease_until=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    session.add(idem)
    await session.commit()
    contract = ChatPersistenceContract(session)
    persisted = await contract.prepare_exchange(
        execution_id="execution-3", request_id="request-3", conversation_id=3,
        organization_id=1, user_id=2, bot_id=4, bot_organization_id=1,
        provider="openai", model="model",
        prompt="hello", idempotency_record_id=idem.id, estimated_tokens=10,
        estimated_cost=10.0, verification=False,
    )
    with pytest.raises(PersistenceConflict, match="ownership"):
        await contract.finalize(
            execution_id=persisted.execution_id, terminal_status="completed", content="answer",
            response_status=200, response_reference="answer", lease_token="intruder",
        )
    execution = (await session.execute(select(ChatExecution))).scalar_one()
    assistant = (await session.execute(select(Message).where(Message.role == "assistant"))).scalar_one()
    refreshed_idem = (await session.execute(select(IdempotencyRecord))).scalar_one()
    assert (execution.status, assistant.status, refreshed_idem.status) == (
        "prepared", "pending", "processing",
    )


def test_alembic_has_one_connected_head():
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["010_conversation_state"]
    revisions = {revision.revision for revision in script.walk_revisions()}
    assert {"000_base_schema", "0019", "002_idempotency_lease", "003_idempotency_lease_token",
            "004_provider_usage", "005_chat_persistence", "006_failure_recovery",
            "007_tenant_isolation", "008_governance_audit"} <= revisions
