from datetime import datetime, timedelta
import inspect

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from eiraos.application.conversation_state import apply_conversation, hydrate_conversation, new_conversation
from eiraos.domains.conversations.models import Conversation
from eiraos.domains.conversations.state import (
    ConversationAggregate,
    ConversationLifecycle,
    ConversationStateError,
)


NOW = datetime(2026, 1, 1)


def test_create_normalizes_title_and_binds_tenant_owner():
    conversation = ConversationAggregate.create(
        organization_id=7, owner_user_id=11, title="  Project Atlas  ", now=NOW,
    )
    assert conversation.title == "Project Atlas"
    assert conversation.lifecycle is ConversationLifecycle.ACTIVE
    assert conversation.version == 1
    assert conversation.organization_id == 7 and conversation.owner_user_id == 11
    conversation.assert_scope(organization_id=7, user_id=11)


@pytest.mark.parametrize("title", ["", "   ", "x" * 256, None])
def test_invalid_titles_fail_closed(title):
    with pytest.raises(ConversationStateError, match="invalid_title"):
        ConversationAggregate.create(
            organization_id=7, owner_user_id=11, title=title, now=NOW,
        )


def test_archive_blocks_execution_and_reopen_is_explicit_versioned_transition():
    active = ConversationAggregate.create(
        organization_id=7, owner_user_id=11, title="Title", now=NOW,
    )
    archived = active.archive(now=NOW + timedelta(seconds=1))
    assert archived.lifecycle is ConversationLifecycle.ARCHIVED
    assert archived.version == 2 and archived.archived_at is not None
    with pytest.raises(ConversationStateError, match="conversation_archived"):
        archived.assert_accepts_execution()
    assert archived.archive().version == 2

    reopened = archived.reopen(now=NOW + timedelta(seconds=2))
    reopened.assert_accepts_execution()
    assert reopened.lifecycle is ConversationLifecycle.ACTIVE
    assert reopened.version == 3 and reopened.archived_at is None


def test_rename_is_domain_owned_and_archived_conversation_cannot_be_renamed():
    active = ConversationAggregate.create(
        organization_id=7, owner_user_id=11, title="Old", now=NOW,
    )
    renamed = active.rename(" New ", now=NOW + timedelta(seconds=1))
    assert renamed.title == "New" and renamed.version == 2
    with pytest.raises(ConversationStateError, match="conversation_archived"):
        renamed.archive(now=NOW + timedelta(seconds=2)).rename("Forbidden")


def test_scope_mismatch_is_rejected():
    aggregate = ConversationAggregate.create(
        organization_id=7, owner_user_id=11, title="Title", now=NOW,
    )
    with pytest.raises(ConversationStateError, match="scope_mismatch"):
        aggregate.assert_scope(organization_id=8, user_id=11)
    with pytest.raises(ConversationStateError, match="scope_mismatch"):
        aggregate.assert_scope(organization_id=7, user_id=12)


def test_orm_mapper_round_trip_preserves_aggregate_state():
    created = ConversationAggregate.create(
        organization_id=7, owner_user_id=11, title="Title", now=NOW,
    )
    row = new_conversation(created)
    row.id = 3
    hydrated = hydrate_conversation(row)
    archived = hydrated.archive(now=NOW + timedelta(seconds=1))
    apply_conversation(row, archived)

    assert row.lifecycle == "archived"
    assert row.version == 2
    assert hydrate_conversation(row) == archived


def test_chat_execution_uses_domain_lifecycle_gate_and_delete_archives():
    from eiraos.api.v1 import chat, conversations

    chat_source = inspect.getsource(chat.create_chat_completion)
    delete_source = inspect.getsource(conversations.delete_conversation)
    assert "assert_accepts_execution" in chat_source
    assert "db.delete" not in delete_source
    assert ".archive()" in delete_source


def test_orm_has_optimistic_version_and_database_lifecycle_constraints():
    assert Conversation.__mapper__.version_id_col is Conversation.__table__.c.version
    constraints = {constraint.name for constraint in Conversation.__table__.constraints}
    assert {
        "ck_conversations_lifecycle",
        "ck_conversations_version_positive",
        "ck_conversations_archive_state",
    } <= constraints


def test_conversation_state_migration_is_single_head():
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["011_memory_runtime"]
    assert script.get_revision("010_conversation_state").down_revision == "009_cost_accounting"