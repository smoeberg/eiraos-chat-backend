import pytest

from eiraos.application.memory import MemoryClass, MemoryItem, MemoryStore, Promotion


def test_memory_classes_are_distinct_and_scoped():
    store = MemoryStore()
    item = MemoryItem("c1", MemoryClass.CONVERSATION_HISTORY, "conv:1", "hello", {})
    store.put(item)
    assert store.get("c1", "conv:1") == item
    assert store.get("c1", "conv:2") is None
    assert MemoryClass.CONVERSATION_HISTORY != MemoryClass.PERSISTENT_MEMORY


def test_persistent_memory_requires_provenance():
    with pytest.raises(ValueError):
        MemoryStore().put(MemoryItem("m1", MemoryClass.PERSISTENT_MEMORY, "user:1", "x", {}))


def test_promotion_is_explicit_and_records_source():
    store = MemoryStore()
    store.put(MemoryItem("c1", MemoryClass.CONVERSATION_HISTORY, "user:1", "fact", {}))
    promoted = store.promote(
        "c1",
        Promotion("user", "explicit save", MemoryClass.PERSISTENT_MEMORY, {"source": "conversation"}),
        new_id="m1",
        content="fact",
    )
    assert promoted.memory_class is MemoryClass.PERSISTENT_MEMORY
    assert promoted.provenance["source_item_id"] == "c1"
    assert promoted.provenance["source_class"] == "conversation_history"


def test_promotion_requires_actor_and_reason():
    store = MemoryStore()
    store.put(MemoryItem("c1", MemoryClass.CONVERSATION_HISTORY, "user:1", "fact", {}))
    with pytest.raises(ValueError):
        store.promote("c1", Promotion("", "", MemoryClass.PERSISTENT_MEMORY, {}), new_id="m1", content="fact")
