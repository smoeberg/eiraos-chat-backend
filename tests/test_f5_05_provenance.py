import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from eiraos.application.memory import MemoryClass
from eiraos.application.memory_runtime import DurableMemoryStore
from eiraos.application.provenance import ProvenanceNotFound, ProvenanceResolver
from eiraos.core.database import Base
from eiraos.domains.conversations.models import Conversation, Message
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
            User(id=1, email="one@provenance.test", username="one-prov", role="member", is_enabled=True),
            User(id=2, email="two@provenance.test", username="two-prov", role="member", is_enabled=True),
            Organization(id=1, name="provenance-one", slug="provenance-one"),
            Organization(id=2, name="provenance-two", slug="provenance-two"),
            OrganizationMember(user_id=1, organization_id=1, role="member"),
            OrganizationMember(user_id=2, organization_id=2, role="owner"),
        ])
        await db.commit()
        yield db
    await engine.dispose()


async def _memory(store, **overrides):
    values = dict(
        organization_id=1, actor_user_id=1, actor_role="member",
        memory_class=MemoryClass.PERSISTENT_MEMORY, scope_kind="user",
        content="fact", provenance={"source": "explicit"}, reason="remember",
    )
    values.update(overrides)
    return await store.create(**values)


@pytest.mark.asyncio
async def test_message_lineage_is_verified_without_exposing_content(session):
    session.add(Conversation(id=20, user_id=1, organization_id=1, title="owned"))
    session.add(Message(id=20, conversation_id=20, organization_id=1, role="user", content="private fact", status="completed"))
    await session.commit()
    item = await _memory(DurableMemoryStore(session), content="private fact", source_message_id=20)

    trace = await ProvenanceResolver(session).trace(item_id=item.item_id, organization_id=1, user_id=1)
    assert trace["termination"] == "source" and trace["complete"]
    assert [node["kind"] for node in trace["nodes"]] == ["memory", "message"]
    assert all("private fact" not in str(node) for node in trace["nodes"])
    assert all(node["integrity"] == "verified" for node in trace["nodes"])


@pytest.mark.asyncio
async def test_memory_chain_retains_deleted_source_as_provenance(session):
    store = DurableMemoryStore(session)
    source = await _memory(store, content="origin")
    child = await _memory(store, content="derived", source_memory_item_id=source.item_id)
    await store.delete(source.item_id, 1, 1, "member")

    trace = await ProvenanceResolver(session).trace(item_id=child.item_id, organization_id=1, user_id=1)
    assert [node["ref"] for node in trace["nodes"]] == [f"memory:{child.item_id}", f"memory:{source.item_id}"]
    assert trace["nodes"][1]["deleted"] is True
    with pytest.raises(ProvenanceNotFound):
        await ProvenanceResolver(session).trace(item_id=source.item_id, organization_id=1, user_id=1)


@pytest.mark.asyncio
async def test_source_mutation_is_reported_as_integrity_failure(session):
    store = DurableMemoryStore(session)
    source = await _memory(store, content="origin")
    child = await _memory(store, content="derived", source_memory_item_id=source.item_id)
    source.content = "tampered"
    await session.commit()

    trace = await ProvenanceResolver(session).trace(item_id=child.item_id, organization_id=1, user_id=1)
    assert trace["termination"] == "integrity_failure"
    assert trace["nodes"][-1]["integrity"] == "source_mismatch"
    assert not trace["complete"]


@pytest.mark.asyncio
async def test_cross_tenant_root_is_indistinguishable_from_missing(session):
    item = await _memory(DurableMemoryStore(session))
    with pytest.raises(ProvenanceNotFound):
        await ProvenanceResolver(session).trace(item_id=item.item_id, organization_id=2, user_id=2)


@pytest.mark.asyncio
async def test_authoritative_provenance_overrides_spoofed_fields(session):
    item = await _memory(
        DurableMemoryStore(session),
        provenance={
            "actor_user_id": 999, "content_sha256": "fake",
            "source_type": "message", "source_message_id": 999,
            "source": "explicit",
        },
    )
    provenance = json.loads(item.provenance_json)
    assert provenance["actor_user_id"] == 1
    assert provenance["content_sha256"] != "fake"
    assert provenance["source_type"] == "declared"
    assert provenance["source_message_id"] is None


@pytest.mark.asyncio
async def test_cycle_and_depth_are_bounded(session):
    store = DurableMemoryStore(session)
    first = await _memory(store, content="first")
    second = await _memory(store, content="second", source_memory_item_id=first.item_id)
    provenance = json.loads(first.provenance_json)
    provenance.update({
        "source_type": "memory",
        "source_memory_item_id": second.item_id,
        "source_sha256": json.loads(second.provenance_json)["content_sha256"],
    })
    first.source_memory_item_id = second.item_id
    first.provenance_json = json.dumps(provenance)
    await session.commit()

    trace = await ProvenanceResolver(session).trace(
        item_id=second.item_id, organization_id=1, user_id=1,
    )
    assert trace["termination"] == "cycle" and not trace["complete"]
    limited = await ProvenanceResolver(session, max_depth=1).trace(
        item_id=second.item_id, organization_id=1, user_id=1,
    )
    assert limited["termination"] == "depth_limit" and not limited["complete"]
    with pytest.raises(ValueError, match="bounded"):
        ProvenanceResolver(session, max_depth=101)