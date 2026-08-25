"""F5-04 explicit memory classes and promotion boundaries."""

from dataclasses import dataclass
from enum import Enum


class MemoryClass(str, Enum):
    CONVERSATION_HISTORY = "conversation_history"
    SHORT_TERM_CONTEXT = "short_term_context"
    PERSISTENT_MEMORY = "persistent_memory"
    USER_ORG_KNOWLEDGE = "user_org_knowledge"


@dataclass(frozen=True, slots=True)
class MemoryItem:
    item_id: str
    memory_class: MemoryClass
    scope: str
    content: object
    provenance: dict


@dataclass(frozen=True, slots=True)
class Promotion:
    actor: str
    reason: str
    target_class: MemoryClass
    provenance: dict


class MemoryStore:
    def __init__(self):
        self._items: dict[str, MemoryItem] = {}

    def put(self, item: MemoryItem) -> None:
        if not item.item_id or not item.scope:
            raise ValueError("memory item requires id and scope")
        if item.memory_class in (MemoryClass.PERSISTENT_MEMORY, MemoryClass.USER_ORG_KNOWLEDGE) and not item.provenance:
            raise ValueError("persistent/knowledge items require provenance")
        self._items[item.item_id] = item

    def get(self, item_id: str, scope: str) -> MemoryItem | None:
        item = self._items.get(item_id)
        if item is None or item.scope != scope:
            return None
        return item

    def promote(self, item_id: str, promotion: Promotion, *, new_id: str, content: object) -> MemoryItem:
        source = self._items.get(item_id)
        if source is None:
            raise KeyError(item_id)
        if not promotion.actor or not promotion.reason:
            raise ValueError("promotion requires actor and reason")
        if source.memory_class == MemoryClass.USER_ORG_KNOWLEDGE and promotion.target_class == MemoryClass.PERSISTENT_MEMORY:
            raise ValueError("cross-owner promotion requires explicit boundary")
        return MemoryItem(
            new_id,
            promotion.target_class,
            source.scope,
            content,
            {**promotion.provenance, "source_item_id": source.item_id, "source_class": source.memory_class.value},
        )
