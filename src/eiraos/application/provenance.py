"""F5-05 tenant-bound, bounded provenance graph resolution."""

from __future__ import annotations

import json

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from eiraos.application.memory_runtime import _sha256
from eiraos.domains.conversations.models import Message
from eiraos.domains.memory.models import MemoryRecord


class ProvenanceNotFound(LookupError):
    pass


class ProvenanceResolver:
    def __init__(self, db: AsyncSession, *, max_depth: int = 20):
        if max_depth <= 0 or max_depth > 100:
            raise ValueError("provenance depth must be bounded")
        self._db = db
        self._max_depth = max_depth

    async def trace(self, *, item_id: str, organization_id: int, user_id: int) -> dict:
        root = await self._memory(item_id, organization_id, user_id, include_deleted=False)
        if root is None:
            raise ProvenanceNotFound(item_id)
        nodes = []
        seen: set[str] = set()
        current = root
        termination = "root"
        for _ in range(self._max_depth):
            ref = f"memory:{current.item_id}"
            if ref in seen:
                termination = "cycle"
                break
            seen.add(ref)
            provenance = self._provenance(current)
            expected = provenance.get("content_sha256")
            actual = _sha256(current.content)
            nodes.append({
                "ref": ref,
                "kind": "memory",
                "memory_class": current.memory_class,
                "scope_kind": current.scope_kind,
                "actor_user_id": current.actor_user_id,
                "reason": current.reason,
                "deleted": current.deleted_at is not None,
                "content_sha256": actual,
                "integrity": "verified" if expected == actual else "mismatch",
            })
            if current.source_memory_item_id:
                source = await self._memory(
                    current.source_memory_item_id, organization_id, user_id,
                    include_deleted=True,
                )
                if source is None:
                    nodes.append({"ref": "unavailable", "kind": "memory", "integrity": "unavailable"})
                    termination = "unavailable"
                    break
                source_expected = provenance.get("source_sha256")
                if source_expected != _sha256(source.content):
                    nodes.append({
                        "ref": f"memory:{source.item_id}", "kind": "memory",
                        "integrity": "source_mismatch",
                    })
                    termination = "integrity_failure"
                    break
                current = source
                continue
            if current.source_message_id:
                message = (await self._db.execute(select(Message).where(
                    Message.id == current.source_message_id,
                    Message.organization_id == organization_id,
                ))).scalar_one_or_none()
                if message is None:
                    nodes.append({"ref": "unavailable", "kind": "message", "integrity": "unavailable"})
                    termination = "unavailable"
                    break
                actual_source = _sha256(message.content)
                nodes.append({
                    "ref": f"message:{message.id}",
                    "kind": "message",
                    "role": message.role,
                    "content_sha256": actual_source,
                    "integrity": "verified" if provenance.get("source_sha256") == actual_source else "source_mismatch",
                })
                termination = "source"
                break
            termination = "declared"
            break
        else:
            termination = "depth_limit"
        return {
            "root_item_id": root.item_id,
            "nodes": nodes,
            "termination": termination,
            "complete": termination in {"source", "declared", "root"},
        }

    async def _memory(self, item_id, organization_id, user_id, *, include_deleted):
        conditions = [
            MemoryRecord.item_id == item_id,
            MemoryRecord.organization_id == organization_id,
            or_(MemoryRecord.scope_kind == "organization", MemoryRecord.owner_user_id == user_id),
        ]
        if not include_deleted:
            conditions.append(MemoryRecord.deleted_at.is_(None))
        return (await self._db.execute(select(MemoryRecord).where(*conditions))).scalar_one_or_none()

    @staticmethod
    def _provenance(record: MemoryRecord) -> dict:
        try:
            value = json.loads(record.provenance_json)
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}