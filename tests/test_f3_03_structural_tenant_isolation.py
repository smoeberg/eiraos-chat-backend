import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from eiraos.application.chat_persistence import ChatPersistenceContract, PersistenceConflict
from eiraos.domains.agents.models import Bot
from eiraos.domains.conversations.models import ChatExecution, Conversation, Message
from eiraos.domains.idempotency.models import IdempotencyRecord
from eiraos.domains.organizations.models import OrganizationMember
from eiraos.domains.usage.models import ProviderUsageRecord


def _foreign_key_names(model) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.foreign_key_constraints
        if constraint.name is not None
    }


def _unique_names(model) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint" and constraint.name
    }


def test_membership_is_a_unique_structural_tenant_anchor():
    assert "uq_org_members_user_org" in _unique_names(OrganizationMember)


def test_conversation_requires_organization_and_membership_pair():
    assert {"fk_conversations_org", "fk_conversations_member"} <= _foreign_key_names(Conversation)
    assert "uq_conversations_id_org" in _unique_names(Conversation)


def test_bot_owner_is_structurally_bound():
    assert "fk_bots_org" in _foreign_key_names(Bot)
    assert "uq_bots_id_org" in _unique_names(Bot)


def test_execution_binds_conversation_member_bot_and_idempotency_tenants():
    assert {
        "fk_chat_executions_org",
        "fk_chat_executions_tenant_conversation",
        "fk_chat_executions_member",
        "fk_chat_executions_bot_owner",
        "fk_chat_executions_tenant_idempotency",
    } <= _foreign_key_names(ChatExecution)
    assert not ChatExecution.__table__.c.bot_organization_id.nullable


def test_message_and_usage_cannot_cross_execution_tenant():
    assert {
        "fk_messages_tenant_conversation",
        "fk_messages_tenant_execution",
    } <= _foreign_key_names(Message)
    assert not Message.__table__.c.organization_id.nullable
    assert "fk_provider_usage_tenant_execution" in _foreign_key_names(ProviderUsageRecord)


def test_idempotency_has_composite_reference_anchor():
    assert "uq_idempotency_id_org_user" in _unique_names(IdempotencyRecord)


def test_persistence_requires_bot_owner_provenance_and_writes_message_tenant():
    signature = inspect.signature(ChatPersistenceContract.prepare_exchange)
    assert signature.parameters["bot_organization_id"].default is inspect.Parameter.empty
    source = inspect.getsource(ChatPersistenceContract.prepare_exchange)
    assert "bot_organization_id=bot_organization_id" in source
    assert source.count("organization_id=organization_id") >= 3


@pytest.mark.asyncio
async def test_replay_cannot_change_bot_owner_tenant_and_releases_lock():
    existing = SimpleNamespace(
        organization_id=1,
        user_id=2,
        conversation_id=3,
        bot_id=4,
        bot_organization_id=9,
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    db = AsyncMock()
    db.execute.return_value = result
    contract = ChatPersistenceContract(db)

    with pytest.raises(PersistenceConflict, match="another scope"):
        await contract.prepare_exchange(
            execution_id="execution",
            request_id="request",
            conversation_id=3,
            organization_id=1,
            user_id=2,
            bot_id=4,
            bot_organization_id=10,
            provider="openai",
            model="model",
            prompt="hello",
            idempotency_record_id=None,
            estimated_tokens=1,
            estimated_cost=1,
            verification=False,
        )
    db.rollback.assert_awaited_once()


def test_f3_03_remains_in_single_migration_chain():
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["010_conversation_state"]
    revision = script.get_revision("007_tenant_isolation")
    assert revision is not None and revision.down_revision == "006_failure_recovery"
