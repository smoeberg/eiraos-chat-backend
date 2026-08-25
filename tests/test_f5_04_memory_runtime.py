import json

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from eiraos.api.v1 import memory as memory_api
from eiraos.application.memory import MemoryClass
from eiraos.application.memory_runtime import DurableMemoryStore, MemoryBoundaryError
from eiraos.core.database import Base
from eiraos.domains.conversations.models import Conversation, Message
from eiraos.domains.identity.models import User
from eiraos.domains.memory.models import MemoryRecord
from eiraos.domains.organizations.models import Organization, OrganizationMember


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        db.add_all([
            User(id=1, email="one@example.test", username="one", role="member", is_enabled=True),
            User(id=2, email="two@example.test", username="two", role="member", is_enabled=True),
            Organization(id=1, name="one", slug="one"),
            Organization(id=2, name="two", slug="two"),
            OrganizationMember(user_id=1, organization_id=1, role="member"),
            OrganizationMember(user_id=2, organization_id=2, role="owner"),
        ])
        await db.commit()
        yield db
    await engine.dispose()


def _create(store, **overrides):
    values = dict(
        organization_id=1,
        actor_user_id=1,
        actor_role="member",
        memory_class=MemoryClass.PERSISTENT_MEMORY,
        scope_kind="user",
        content="remember this",
        provenance={"source": "explicit-user-action"},
        reason="save for later",
    )
    values.update(overrides)
    return store.create(**values)


@pytest.mark.asyncio
async def test_durable_user_memory_is_scope_bound_and_soft_deletable(session):
    store = DurableMemoryStore(session)
    item = await _create(store)

    assert await store.get(item.item_id, 1, 1) == item
    assert await store.get(item.item_id, 2, 2) is None
    assert json.loads(item.provenance_json)["source"] == "explicit-user-action"
    assert await store.delete(item.item_id, 1, 1, "member")
    assert await store.get(item.item_id, 1, 1) is None


@pytest.mark.asyncio
async def test_ephemeral_classes_and_unattributed_writes_fail_closed(session):
    store = DurableMemoryStore(session)
    with pytest.raises(MemoryBoundaryError, match="ephemeral"):
        await _create(store, memory_class=MemoryClass.SHORT_TERM_CONTEXT)
    with pytest.raises(MemoryBoundaryError, match="provenance"):
        await _create(store, provenance={})


@pytest.mark.asyncio
async def test_member_cannot_mutate_organization_memory(session):
    with pytest.raises(PermissionError, match="admin"):
        await _create(
            DurableMemoryStore(session),
            memory_class=MemoryClass.USER_ORG_KNOWLEDGE,
            scope_kind="organization",
        )


@pytest.mark.asyncio
async def test_message_promotion_requires_completed_tenant_visible_source(session):
    session.add(Conversation(id=1, user_id=1, organization_id=1, title="owned"))
    session.add(Message(id=10, conversation_id=1, organization_id=1, role="user", content="fact", status="completed"))
    await session.commit()

    promoted = await _create(DurableMemoryStore(session), source_message_id=10)
    assert json.loads(promoted.provenance_json)["source_message_id"] == 10
    with pytest.raises(MemoryBoundaryError, match="unavailable"):
        await _create(DurableMemoryStore(session), source_message_id=999)


def test_memory_api_is_capability_gated_and_migration_is_head():
    permissions = set()
    for route in memory_api.router.routes:
        for dependency in route.dependant.dependencies:
            call = dependency.call
            for cell in (call.__closure__ or []) if call else []:
                if isinstance(cell.cell_contents, str) and ":" in cell.cell_contents:
                    permissions.add(cell.cell_contents)
    assert permissions == {"memory:read", "memory:write", "memory:delete"}
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    assert scripts.get_current_head() == "012_agent_audit"
    constraints = {constraint.name for constraint in MemoryRecord.__table__.constraints}
    assert "uq_memory_records_item_id" in constraints