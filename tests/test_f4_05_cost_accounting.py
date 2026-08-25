from decimal import Decimal

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from eiraos.application.chat_persistence import ChatPersistenceContract
from eiraos.application.cost_accounting import (
    CostAccountingUnavailable,
    ExecutionCost,
    ExecutionCostAccountant,
)
from eiraos.core.database import Base
from eiraos.domains.idempotency.models import IdempotencyRecord
from eiraos.domains.usage.models import ProviderUsageRecord


def test_cost_is_deterministic_from_versioned_model_price():
    cost = ExecutionCostAccountant().account(
        provider="OpenAI",
        model="gpt-4o-mini",
        operation="primary",
        messages=[{"role": "user", "content": "abcd"}],
        output="wxyz",
    )

    assert (cost.input_tokens, cost.output_tokens, cost.total_tokens) == (1, 1, 2)
    assert cost.cost == Decimal("0.0000007500")
    assert cost.usage_source == "estimated"
    assert cost.pricing_revision


def test_system_prompt_and_history_are_included_in_input_usage():
    cost = ExecutionCostAccountant().account(
        provider="claude",
        model="claude-3-5-haiku-20241022",
        operation="verification",
        messages=[{"role": "user", "content": "1234"}, {"role": "assistant", "content": "5678"}],
        output="ok",
        system_prompt="abcd",
    )
    assert cost.provider == "anthropic"
    assert cost.input_tokens == 3
    assert cost.output_tokens == 1


def test_uncatalogued_model_cannot_be_priced():
    with pytest.raises(CostAccountingUnavailable):
        ExecutionCostAccountant().account(
            provider="openai", model="unknown", operation="primary",
            messages=[], output="answer",
        )
    with pytest.raises(CostAccountingUnavailable):
        ExecutionCostAccountant().account(
            provider="unknown", model="model", operation="primary",
            messages=[], output="answer",
        )


def test_invalid_accounting_metadata_fails_closed():
    with pytest.raises(ValueError, match="total tokens"):
        ExecutionCost("openai", "model", "primary", 1, 1, 3, Decimal("0"), "estimated", "revision")
    with pytest.raises(ValueError, match="operation"):
        ExecutionCost("openai", "model", "other", 1, 1, 2, Decimal("0"), "estimated", "revision")


@pytest.mark.asyncio
async def test_terminal_transition_atomically_appends_primary_and_verifier_ledger_rows():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        idem = IdempotencyRecord(
            organization_id=1, user_id=2, key="key", request_hash="a" * 64,
            status="processing", lease_token="lease",
        )
        session.add(idem)
        await session.commit()
        contract = ChatPersistenceContract(session)
        persisted = await contract.prepare_exchange(
            execution_id="execution", request_id="request", conversation_id=3,
            organization_id=1, user_id=2, bot_id=4, bot_organization_id=1,
            provider="openai", model="gpt-4o-mini", prompt="hello",
            idempotency_record_id=idem.id, estimated_tokens=100,
            estimated_cost=Decimal("1"), verification=True,
        )
        accountant = ExecutionCostAccountant()
        primary = accountant.account(
            provider="openai", model="gpt-4o-mini", operation="primary",
            messages=[{"role": "user", "content": "hello"}], output="answer",
        )
        verifier = accountant.account(
            provider="anthropic", model="claude-3-5-haiku-20241022",
            operation="verification",
            messages=[{"role": "user", "content": "check"}], output='{"status":"PASS"}',
        )

        assert await contract.finalize(
            execution_id=persisted.execution_id, terminal_status="completed",
            content="answer", response_status=200, response_reference="response",
            lease_token="lease", accounting=(primary, verifier),
        )
        rows = (await session.execute(
            select(ProviderUsageRecord).order_by(ProviderUsageRecord.id)
        )).scalars().all()

        assert [row.usage_source for row in rows] == ["reservation", "estimated", "estimated"]
        assert [row.operation for row in rows] == ["reservation", "primary", "verification"]
        assert rows[0].total_tokens == 100 and rows[0].actual_cost is None
        assert rows[1].total_tokens == primary.total_tokens
        assert rows[1].actual_cost == primary.cost
        assert rows[2].provider == "anthropic" and rows[2].verification
        assert not await contract.finalize(
            execution_id=persisted.execution_id, terminal_status="completed",
            content="duplicate", response_status=200, response_reference="duplicate",
            lease_token="lease", accounting=(primary,),
        )
        assert len((await session.execute(select(ProviderUsageRecord))).scalars().all()) == 3
    await engine.dispose()


def test_cost_accounting_migration_is_single_head():
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["012_agent_audit"]


def test_ledger_exactly_once_key_exists_in_runtime_schema():
    names = {constraint.name for constraint in ProviderUsageRecord.__table__.constraints}
    assert "uq_provider_usage_execution_attempt_operation_source" in names