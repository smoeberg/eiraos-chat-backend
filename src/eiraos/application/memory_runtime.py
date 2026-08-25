"""F5-04 durable, tenant-bound memory runtime."""

from __future__ import annotations

from datetime import datetime
import json
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from eiraos.application.memory import MemoryClass
from eiraos.domains.conversations.models import Conversation, Message
from eiraos.domains.memory.models import MemoryRecord


class MemoryBoundaryError(ValueError):
    pass


class DurableMemoryStore:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def create(
        self, *, organization_id: int, actor_user_id: int, actor_role: str,
        memory_class: MemoryClass, scope_kind: str, content: str,
        provenance: dict, reason: str, source_message_id: int | None = None,
        source_memory_item_id: str | None = None,
    ) -> MemoryRecord:
        self._validate(memory_class, scope_kind, content, provenance, reason)
        self._assert_mutation_scope(scope_kind, actor_role)
        if source_message_id is not None:
            await self._assert_message_source(
                source_message_id, organization_id, actor_user_id, scope_kind,
            )
        source = None
        if source_memory_item_id is not None:
            source = await self.get(source_memory_item_id, organization_id, actor_user_id)
            if source is None:
                raise MemoryBoundaryError("source memory is unavailable in caller scope")
        record = MemoryRecord(
            item_id=uuid.uuid4().hex,
            organization_id=organization_id,
            owner_user_id=actor_user_id if scope_kind == "user" else None,
            actor_user_id=actor_user_id,
            memory_class=memory_class.value,
            scope_kind=scope_kind,
            content=content.strip(),
            provenance_json=json.dumps({
                **provenance,
                **({"source_memory_item_id": source.item_id} if source else {}),
                **({"source_message_id": source_message_id} if source_message_id else {}),
            }, sort_keys=True, separators=(",", ":")),
            source_message_id=source_message_id,
            source_memory_item_id=source.item_id if source else None,
            reason=reason.strip(),
        )
        self._db.add(record)
        await self._db.commit()
        await self._db.refresh(record)
        return record

    async def get(
        self, item_id: str, organization_id: int, user_id: int,
    ) -> MemoryRecord | None:
        return (await self._db.execute(select(MemoryRecord).where(
            MemoryRecord.item_id == item_id,
            MemoryRecord.organization_id == organization_id,
            MemoryRecord.deleted_at.is_(None),
            or_(
                MemoryRecord.scope_kind == "organization",
                MemoryRecord.owner_user_id == user_id,
            ),
        ))).scalar_one_or_none()

    async def list(self, organization_id: int, user_id: int) -> list[MemoryRecord]:
        return list((await self._db.execute(select(MemoryRecord).where(
            MemoryRecord.organization_id == organization_id,
            MemoryRecord.deleted_at.is_(None),
            or_(MemoryRecord.scope_kind == "organization", MemoryRecord.owner_user_id == user_id),
        ).order_by(MemoryRecord.created_at.desc(), MemoryRecord.id.desc()))).scalars().all())

    async def delete(
        self, item_id: str, organization_id: int, user_id: int, actor_role: str,
    ) -> bool:
        record = await self.get(item_id, organization_id, user_id)
        if record is None:
            return False
        self._assert_mutation_scope(record.scope_kind, actor_role)
        record.deleted_at = datetime.utcnow()
        await self._db.commit()
        return True

    async def _assert_message_source(
        self, message_id: int, organization_id: int, user_id: int, scope_kind: str,
    ) -> None:
        stmt = select(Message.id).join(
            Conversation,
            (Conversation.id == Message.conversation_id)
            & (Conversation.organization_id == Message.organization_id),
        ).where(
            Message.id == message_id,
            Message.organization_id == organization_id,
            Message.status == "completed",
        )
        if scope_kind == "user":
            stmt = stmt.where(Conversation.user_id == user_id)
        if (await self._db.execute(stmt)).scalar_one_or_none() is None:
            raise MemoryBoundaryError("source message is unavailable in target scope")

    @staticmethod
    def _assert_mutation_scope(scope_kind: str, actor_role: str) -> None:
        if scope_kind == "organization" and actor_role not in {"owner", "admin"}:
            raise PermissionError("organization memory mutation requires admin authority")

    @staticmethod
    def _validate(memory_class, scope_kind, content, provenance, reason) -> None:
        if memory_class not in {MemoryClass.PERSISTENT_MEMORY, MemoryClass.USER_ORG_KNOWLEDGE}:
            raise MemoryBoundaryError("ephemeral memory classes cannot be persisted")
        if scope_kind not in {"user", "organization"}:
            raise MemoryBoundaryError("memory scope must be explicit")
        if not isinstance(content, str) or not content.strip() or len(content) > 20_000:
            raise MemoryBoundaryError("memory content is invalid")
        if not isinstance(provenance, dict) or not provenance:
            raise MemoryBoundaryError("durable memory requires provenance")
        if not isinstance(reason, str) or not reason.strip():
            raise MemoryBoundaryError("memory operation requires a reason")