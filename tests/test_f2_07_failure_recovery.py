import asyncio
import inspect
from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import AsyncMock
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from eiraos.application.chat_persistence import (
    ChatPersistenceContract,
    PersistenceConflict,
    RetryLimitExceeded,
)
from eiraos.application.chat_recovery import (
    FailureCode,
    failure_policy,
    provider_with_timeout,
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


async def _owned_execution(session, *, execution_id="execution", max_attempts=3):
    idem = IdempotencyRecord(
        organization_id=1,
        user_id=2,
        key="key",
        request_hash="a" * 64,
        status="processing",
        lease_token="lease-1",
        lease_until=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    session.add(idem)
    await session.commit()
    contract = ChatPersistenceContract(session)
    persisted = await contract.prepare_exchange(
        execution_id=execution_id,
        request_id="request",
        conversation_id=3,
        organization_id=1,
        user_id=2,
        bot_id=4,
        bot_organization_id=1,
        provider="openai",
        model="model",
        prompt="hello",
        idempotency_record_id=idem.id,
        estimated_tokens=10,
        estimated_cost=1.0,
        verification=False,
        max_attempts=max_attempts,
    )
    return contract, idem, persisted


def test_failure_policy_is_explicit_and_failures_are_not_equivalent():
    assert failure_policy(FailureCode.PROVIDER_TIMEOUT).response_status == 504
    assert failure_policy(FailureCode.PROVIDER_TIMEOUT).retryable
    assert not failure_policy(FailureCode.BUDGET_REJECTED).retryable
    assert not failure_policy(FailureCode.IDEMPOTENCY_CONFLICT).retryable


def test_primary_and_verifier_provider_calls_share_the_timeout_boundary():
    from eiraos.api.v1.chat import create_chat_completion

    source = inspect.getsource(create_chat_completion)
    assert source.count("provider_isolation.execute(") == 3


@pytest.mark.asyncio
async def test_nonstream_provider_deadline_cancels_stalled_operation():
    cancelled = asyncio.Event()

    async def stalled():
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    with pytest.raises(asyncio.TimeoutError):
        await provider_with_timeout(stalled(), 0.01)
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_partial_provider_failure_is_durable_and_retryable(session):
    contract, _, persisted = await _owned_execution(session)
    policy = failure_policy(FailureCode.PROVIDER_FAILURE)
    assert await contract.finalize(
        execution_id=persisted.execution_id,
        terminal_status="failed",
        content="partial answer",
        response_status=policy.response_status,
        response_reference="failed",
        lease_token="lease-1",
        failure_code=FailureCode.PROVIDER_FAILURE,
    )
    execution = (await session.execute(select(ChatExecution))).scalar_one()
    assistant = (await session.execute(select(Message).where(Message.role == "assistant"))).scalar_one()
    assert (execution.status, execution.last_failure_code) == ("failed", "provider_failure")
    assert execution.failure_retryable and execution.partial_response
    assert assistant.content == "partial answer"


@pytest.mark.asyncio
async def test_database_finalize_failure_rolls_back_the_entire_terminal_transition(
    session, monkeypatch,
):
    contract, _, persisted = await _owned_execution(session)
    original_commit = session.commit
    monkeypatch.setattr(session, "commit", AsyncMock(side_effect=RuntimeError("database down")))
    from eiraos.application.chat_persistence import PersistenceUnavailable

    with pytest.raises(PersistenceUnavailable):
        await contract.finalize(
            execution_id=persisted.execution_id,
            terminal_status="failed",
            content="partial",
            response_status=502,
            response_reference="failed",
            lease_token="lease-1",
            failure_code=FailureCode.PROVIDER_FAILURE,
        )
    monkeypatch.setattr(session, "commit", original_commit)
    execution = (await session.execute(select(ChatExecution))).scalar_one()
    assistant = (await session.execute(select(Message).where(Message.role == "assistant"))).scalar_one()
    assert execution.status == "prepared"
    assert assistant.status == "pending"
    assert assistant.content == ""


@pytest.mark.asyncio
async def test_failed_execution_retry_requires_new_owned_lease_and_reuses_rows(session):
    contract, idem, persisted = await _owned_execution(session, max_attempts=2)
    policy = failure_policy(FailureCode.PROVIDER_TIMEOUT)
    await contract.finalize(
        execution_id=persisted.execution_id,
        terminal_status="failed",
        content="partial",
        response_status=policy.response_status,
        response_reference="failed",
        lease_token="lease-1",
        failure_code=FailureCode.PROVIDER_TIMEOUT,
    )
    idem.status = "processing"
    idem.lease_token = "lease-2"
    idem.lease_until = datetime.now(timezone.utc) + timedelta(minutes=1)
    await session.commit()

    retried = await contract.prepare_exchange(
        execution_id=persisted.execution_id,
        request_id="request-2",
        conversation_id=3,
        organization_id=1,
        user_id=2,
        bot_id=4,
        bot_organization_id=1,
        provider="openai",
        model="model",
        prompt="hello",
        idempotency_record_id=idem.id,
        estimated_tokens=10,
        estimated_cost=1.0,
        verification=False,
        recover=True,
        lease_token="lease-2",
    )
    execution = (await session.execute(select(ChatExecution))).scalar_one()
    messages = (await session.execute(select(Message).order_by(Message.id))).scalars().all()
    usage = (await session.execute(select(ProviderUsageRecord))).scalar_one()
    assert retried.status == "prepared"
    assert execution.attempt_count == 2
    assert execution.last_failure_code == "provider_timeout"
    assert len(messages) == 2
    assert messages[1].content == "" and messages[1].status == "pending"
    assert usage.total_tokens == 20
    assert float(usage.estimated_cost) == 2.0


@pytest.mark.asyncio
async def test_process_crash_recovery_is_lease_owned_and_bounded(session):
    contract, idem, persisted = await _owned_execution(session, max_attempts=2)
    idem_id = idem.id
    idem.lease_token = "lease-2"
    idem.lease_until = datetime.now(timezone.utc) + timedelta(minutes=1)
    await session.commit()

    with pytest.raises(PersistenceConflict, match="ownership"):
        await contract.prepare_exchange(
            execution_id=persisted.execution_id,
            request_id="request-2",
            conversation_id=3,
            organization_id=1,
            user_id=2,
            bot_id=4,
            bot_organization_id=1,
            provider="openai",
            model="model",
            prompt="hello",
            idempotency_record_id=idem_id,
            estimated_tokens=10,
            estimated_cost=1.0,
            verification=False,
            recover=True,
            lease_token="stale-owner",
        )

    await contract.prepare_exchange(
        execution_id=persisted.execution_id,
        request_id="request-2",
        conversation_id=3,
        organization_id=1,
        user_id=2,
        bot_id=4,
        bot_organization_id=1,
        provider="openai",
        model="model",
        prompt="hello",
        idempotency_record_id=idem_id,
        estimated_tokens=10,
        estimated_cost=1.0,
        verification=False,
        recover=True,
        lease_token="lease-2",
    )
    execution = (await session.execute(select(ChatExecution))).scalar_one()
    assert execution.attempt_count == 2
    assert execution.last_failure_code == "process_crash"
    assert execution.recovered_at is not None

    idem = await session.get(IdempotencyRecord, idem_id)
    assert idem is not None
    idem.lease_token = "lease-3"
    idem.lease_until = datetime.now(timezone.utc) + timedelta(minutes=1)
    await session.commit()
    with pytest.raises(RetryLimitExceeded):
        await contract.assert_recovery_allowed(
            execution_id=persisted.execution_id,
            idempotency_record_id=idem_id,
            lease_token="lease-3",
        )
    execution = (await session.execute(select(ChatExecution))).scalar_one()
    idem = await session.get(IdempotencyRecord, idem_id)
    assert execution.status == "failed"
    assert execution.last_failure_code == "retry_exhausted"
    assert not execution.failure_retryable
    assert idem is not None and idem.status == "failed"


def test_migrations_remain_single_head_after_f2_07():
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["008_governance_audit"]
