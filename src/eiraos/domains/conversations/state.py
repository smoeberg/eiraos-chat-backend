"""F5-01 conversation aggregate and lifecycle invariants."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum


class ConversationLifecycle(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class ConversationStateError(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _title(value: str) -> str:
    if not isinstance(value, str):
        raise ConversationStateError("invalid_title")
    normalized = value.strip()
    if not normalized or len(normalized) > 255:
        raise ConversationStateError("invalid_title")
    return normalized


@dataclass(frozen=True, slots=True)
class ConversationAggregate:
    id: int | None
    organization_id: int
    owner_user_id: int
    title: str
    lifecycle: ConversationLifecycle
    version: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.id is not None and self.id <= 0:
            raise ConversationStateError("invalid_identity")
        if self.organization_id <= 0 or self.owner_user_id <= 0:
            raise ConversationStateError("invalid_scope")
        if self.version <= 0:
            raise ConversationStateError("invalid_version")
        object.__setattr__(self, "title", _title(self.title))
        if self.lifecycle is ConversationLifecycle.ACTIVE and self.archived_at is not None:
            raise ConversationStateError("active_conversation_has_archive_time")
        if self.lifecycle is ConversationLifecycle.ARCHIVED and self.archived_at is None:
            raise ConversationStateError("archived_conversation_missing_archive_time")

    @classmethod
    def create(
        cls, *, organization_id: int, owner_user_id: int, title: str,
        now: datetime | None = None,
    ) -> "ConversationAggregate":
        timestamp = now or datetime.utcnow()
        return cls(
            id=None,
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            title=title,
            lifecycle=ConversationLifecycle.ACTIVE,
            version=1,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def assert_scope(self, *, organization_id: int, user_id: int) -> None:
        if organization_id != self.organization_id or user_id != self.owner_user_id:
            raise ConversationStateError("scope_mismatch")

    def assert_accepts_execution(self) -> None:
        if self.lifecycle is not ConversationLifecycle.ACTIVE:
            raise ConversationStateError("conversation_archived")

    def rename(self, title: str, *, now: datetime | None = None) -> "ConversationAggregate":
        self.assert_accepts_execution()
        return self._transition(title=_title(title), updated_at=now or datetime.utcnow())

    def archive(self, *, now: datetime | None = None) -> "ConversationAggregate":
        if self.lifecycle is ConversationLifecycle.ARCHIVED:
            return self
        timestamp = now or datetime.utcnow()
        return self._transition(
            lifecycle=ConversationLifecycle.ARCHIVED,
            archived_at=timestamp,
            updated_at=timestamp,
        )

    def reopen(self, *, now: datetime | None = None) -> "ConversationAggregate":
        if self.lifecycle is ConversationLifecycle.ACTIVE:
            return self
        return self._transition(
            lifecycle=ConversationLifecycle.ACTIVE,
            archived_at=None,
            updated_at=now or datetime.utcnow(),
        )

    def _transition(self, **changes) -> "ConversationAggregate":
        return replace(self, version=self.version + 1, **changes)
