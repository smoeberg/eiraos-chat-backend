"""F8-02 integrity/concurrency/recovery qualification on migrated PostgreSQL."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from conftest_postgres import require_postgres
from eiraos.application.chat_persistence import ChatPersistenceContract, RetryLimitExceeded


@pytest.fixture
async def pg_factory():
    engine = create_async_engine(require_postgres(), pool_size=10, max_overflow=10)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def seed_execution(factory, *, max_attempts=3):
    suffix = uuid.uuid4().hex
    async with factory() as session:
        org_id = (await session.execute(text(
            "INSERT INTO organizations (name, slug) VALUES (:n, :s) RETURNING id"
        ), {"n": f"f8-org-{suffix}", "s": f"f8-org-{suffix}"})).scalar_one()
        other_org_id = (await session.execute(text(
            "INSERT INTO organizations (name, slug) VALUES (:n, :s) RETURNING id"
        ), {"n": f"f8-other-{suffix}", "s": f"f8-other-{suffix}"})).scalar_one()
        user_id = (await session.execute(text(
            "INSERT INTO users (email, username, role, is_enabled, token_version) "
            "VALUES (:e, :e, 'member', true, 1) RETURNING id"
        ), {"e": f"f8-{suffix}@example.com"})).scalar_one()
        await session.execute(text(
            "INSERT INTO organization_members (organization_id, user_id, role) "
            "VALUES (:o, :u, 'owner'), (:other, :u, 'owner')"
        ), {"o": org_id, "other": other_org_id, "u": user_id})
        bot_id = (await session.execute(text(
            "INSERT INTO bots (organization_id, title) VALUES (:o, :t) RETURNING id"
        ), {"o": org_id, "t": f"f8-bot-{suffix}"})).scalar_one()
        conversation_id = (await session.execute(text(
            "INSERT INTO conversations (user_id, organization_id, title) "
            "VALUES (:u, :o, :t) RETURNING id"
        ), {"u": user_id, "o": org_id, "t": "F8 qualification"})).scalar_one()
        idem_id = (await session.execute(text(
            "INSERT INTO idempotency_records "
            "(organization_id, user_id, key, request_hash, status, lease_token, lease_until) "
            "VALUES (:o, :u, :k, :h, 'processing', 'lease-1', :until) RETURNING id"
        ), {
            "o": org_id, "u": user_id, "k": f"f8-{suffix}", "h": "a" * 64,
            "until": datetime.utcnow() + timedelta(minutes=5),
        })).scalar_one()
        await session.commit()
        execution_id = f"f8-{suffix}"
        persisted = await ChatPersistenceContract(session).prepare_exchange(
            execution_id=execution_id, request_id=f"request-{suffix}",
            conversation_id=conversation_id, organization_id=org_id,
            user_id=user_id, bot_id=bot_id, bot_organization_id=org_id,
            provider="openai", model="gpt-test", prompt="hello",
            idempotency_record_id=idem_id, estimated_tokens=10,
            estimated_cost=0.1, verification=False, max_attempts=max_attempts,
        )
    return {
        "suffix": suffix, "org": org_id, "other_org": other_org_id,
        "user": user_id, "bot": bot_id, "conversation": conversation_id,
        "idem": idem_id, "execution": persisted.execution_id,
    }


async def cleanup(factory, ids):
    async with factory() as session:
        params = {"e": ids["execution"], "i": ids["idem"], "c": ids["conversation"],
                  "b": ids["bot"], "u": ids["user"], "o": ids["org"],
                  "other": ids["other_org"]}
        for statement in (
            "DELETE FROM provider_usage_records WHERE execution_id=:e",
            "UPDATE chat_executions SET user_message_id=NULL, assistant_message_id=NULL WHERE execution_id=:e",
            "DELETE FROM messages WHERE execution_id=:e",
            "DELETE FROM chat_executions WHERE execution_id=:e",
            "DELETE FROM idempotency_records WHERE id=:i",
            "DELETE FROM conversations WHERE id=:c",
            "DELETE FROM bots WHERE id=:b",
            "DELETE FROM organization_members WHERE user_id=:u",
            "DELETE FROM users WHERE id=:u",
            "DELETE FROM organizations WHERE id IN (:o, :other)",
        ):
            await session.execute(text(statement), params)
        await session.commit()


@pytest.mark.asyncio
async def test_postgres_qualification_enforces_tenant_and_assistant_constraints(pg_factory):
    ids = await seed_execution(pg_factory)
    try:
        async with pg_factory() as session:
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    await session.execute(text(
                        "INSERT INTO messages (conversation_id, organization_id, execution_id, role, content) "
                        "VALUES (:c, :other, :e, 'system', 'cross tenant')"
                    ), {"c": ids["conversation"], "other": ids["other_org"], "e": ids["execution"]})
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    await session.execute(text(
                        "INSERT INTO messages (conversation_id, organization_id, execution_id, role, content) "
                        "VALUES (:c, :o, :e, 'assistant', 'duplicate')"
                    ), {"c": ids["conversation"], "o": ids["org"], "e": ids["execution"]})
    finally:
        await cleanup(pg_factory, ids)


@pytest.mark.asyncio
async def test_postgres_qualification_parallel_finalization_has_one_winner(pg_factory):
    ids = await seed_execution(pg_factory)
    try:
        async def finalize():
            async with pg_factory() as session:
                return await ChatPersistenceContract(session).finalize(
                    execution_id=ids["execution"], terminal_status="completed",
                    content="answer", response_status=200,
                    response_reference='{"content":"answer"}', lease_token="lease-1",
                )

        results = await asyncio.gather(finalize(), finalize())
        assert sorted(results) == [False, True]
        async with pg_factory() as session:
            row = (await session.execute(text(
                "SELECT e.status, m.status, m.content, i.status, "
                "(SELECT count(*) FROM messages WHERE execution_id=:e AND role='assistant') AS assistants "
                "FROM chat_executions e JOIN messages m ON m.id=e.assistant_message_id "
                "JOIN idempotency_records i ON i.id=e.idempotency_record_id "
                "WHERE e.execution_id=:e"
            ), {"e": ids["execution"]})).one()
        assert tuple(row) == ("completed", "completed", "answer", "completed", 1)
    finally:
        await cleanup(pg_factory, ids)


@pytest.mark.asyncio
async def test_postgres_qualification_crash_recovery_is_bounded_and_reuses_rows(pg_factory):
    ids = await seed_execution(pg_factory, max_attempts=2)
    try:
        async with pg_factory() as session:
            await session.execute(text(
                "UPDATE chat_executions SET status='streaming' WHERE execution_id=:e"
            ), {"e": ids["execution"]})
            await session.execute(text(
                "UPDATE messages SET status='streaming', content='partial' "
                "WHERE execution_id=:e AND role='assistant'"
            ), {"e": ids["execution"]})
            await session.execute(text(
                "UPDATE idempotency_records SET lease_token='lease-2', lease_until=:until WHERE id=:i"
            ), {"i": ids["idem"], "until": datetime.utcnow() + timedelta(minutes=5)})
            await session.commit()
            await ChatPersistenceContract(session).prepare_exchange(
                execution_id=ids["execution"], request_id="recovery",
                conversation_id=ids["conversation"], organization_id=ids["org"],
                user_id=ids["user"], bot_id=ids["bot"], bot_organization_id=ids["org"],
                provider="openai", model="gpt-test", prompt="hello",
                idempotency_record_id=ids["idem"], estimated_tokens=10,
                estimated_cost=0.1, verification=False, recover=True,
                lease_token="lease-2", max_attempts=2,
            )
            state = (await session.execute(text(
                "SELECT e.status, e.attempt_count, e.last_failure_code, m.status, m.content, "
                "(SELECT count(*) FROM messages WHERE execution_id=:e) "
                "FROM chat_executions e JOIN messages m ON m.id=e.assistant_message_id "
                "WHERE e.execution_id=:e"
            ), {"e": ids["execution"]})).one()
            assert tuple(state) == ("prepared", 2, "process_crash", "pending", "", 2)
            await session.execute(text(
                "UPDATE idempotency_records SET lease_token='lease-3', lease_until=:until WHERE id=:i"
            ), {"i": ids["idem"], "until": datetime.utcnow() + timedelta(minutes=5)})
            await session.commit()
            with pytest.raises(RetryLimitExceeded):
                await ChatPersistenceContract(session).assert_recovery_allowed(
                    execution_id=ids["execution"], idempotency_record_id=ids["idem"],
                    lease_token="lease-3",
                )
            exhausted = (await session.execute(text(
                "SELECT status, last_failure_code, failure_retryable FROM chat_executions "
                "WHERE execution_id=:e"
            ), {"e": ids["execution"]})).one()
            assert tuple(exhausted) == ("failed", "retry_exhausted", False)
    finally:
        await cleanup(pg_factory, ids)
