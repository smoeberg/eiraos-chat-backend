"""F2-06 atomic persistence contract for one chat execution."""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eiraos.domains.conversations.models import ChatExecution, Message
from eiraos.domains.idempotency.models import IdempotencyRecord
from eiraos.domains.usage.models import ProviderUsageRecord


TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


class PersistenceConflict(RuntimeError):
    """Raised when durable state no longer permits the requested transition."""


@dataclass(frozen=True)
class PersistedChatExecution:
    execution_id: str
    user_message_id: int
    assistant_message_id: int
    status: str


def execution_identity(*, organization_id: int, user_id: int, idempotency_key: str | None) -> str:
    """Return a replay-stable identity when idempotency is present."""
    if not idempotency_key:
        return uuid.uuid4().hex
    material = f"{organization_id}:{user_id}:{idempotency_key}".encode()
    return hashlib.sha256(material).hexdigest()


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


class ChatPersistenceContract:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def prepare_exchange(
        self,
        *,
        execution_id: str,
        request_id: str,
        conversation_id: int,
        organization_id: int,
        user_id: int,
        bot_id: int,
        provider: str,
        model: str,
        prompt: str,
        idempotency_record_id: int | None,
        estimated_tokens: int,
        estimated_cost: float,
        verification: bool,
    ) -> PersistedChatExecution:
        existing = (await self._db.execute(select(ChatExecution).where(
            ChatExecution.execution_id == execution_id,
        ).with_for_update())).scalar_one_or_none()
        if existing is not None:
            if (
                existing.organization_id != organization_id
                or existing.user_id != user_id
                or existing.conversation_id != conversation_id
                or existing.bot_id != bot_id
            ):
                raise PersistenceConflict("execution identity is bound to another scope")
            if existing.status == "failed":
                assistant = await self._assistant(existing)
                assistant.content = ""
                assistant.status = "pending"
                existing.status = "prepared"
                existing.completed_at = None
                await self._db.commit()
            return self._snapshot(existing)

        execution = ChatExecution(
            execution_id=execution_id,
            request_id=request_id,
            conversation_id=conversation_id,
            organization_id=organization_id,
            user_id=user_id,
            bot_id=bot_id,
            idempotency_record_id=idempotency_record_id,
            provider=provider,
            model=model,
            status="prepared",
        )
        user_message = Message(
            conversation_id=conversation_id, execution_id=execution_id,
            role="user", content=prompt, bot_id=bot_id,
            status="completed", ai_marked=False,
        )
        assistant_message = Message(
            conversation_id=conversation_id, execution_id=execution_id,
            role="assistant", content="", bot_id=bot_id,
            status="pending", ai_marked=True,
        )
        try:
            self._db.add_all([execution, user_message, assistant_message])
            await self._db.flush()
            execution.user_message_id = user_message.id
            execution.assistant_message_id = assistant_message.id
            await self._db.flush()
        except Exception:
            await self._db.rollback()
            raise
        usage = ProviderUsageRecord(
            request_id=request_id,
            execution_id=execution_id,
            chat_execution_id=execution.id,
            user_id=user_id,
            organization_id=organization_id,
            provider=provider,
            model=model,
            total_tokens=estimated_tokens,
            estimated_cost=Decimal(str(estimated_cost)),
            verification=verification,
        )
        try:
            self._db.add(usage)
            await self._db.commit()
        except Exception:
            await self._db.rollback()
            raise
        return self._snapshot(execution)

    async def mark_streaming(self, execution_id: str) -> bool:
        execution = await self._locked_execution(execution_id)
        if execution.status in TERMINAL_STATUSES:
            return False
        assistant = await self._assistant(execution)
        execution.status = "streaming"
        assistant.status = "streaming"
        await self._db.commit()
        return True

    async def finalize(
        self,
        *,
        execution_id: str,
        terminal_status: str,
        content: str,
        response_status: int,
        response_reference: str,
        lease_token: str | None,
    ) -> bool:
        if terminal_status not in TERMINAL_STATUSES:
            raise ValueError("terminal_status must be completed, failed or cancelled")
        execution = await self._locked_execution(execution_id)
        if execution.status in TERMINAL_STATUSES:
            await self._db.rollback()
            return False

        idem = None
        if execution.idempotency_record_id is not None:
            idem = (await self._db.execute(select(IdempotencyRecord).where(
                IdempotencyRecord.id == execution.idempotency_record_id,
            ).with_for_update())).scalar_one_or_none()
            if idem is None or idem.status != "processing" or idem.lease_token != lease_token:
                await self._db.rollback()
                raise PersistenceConflict("idempotency ownership was lost")
            lease_until = _as_utc(idem.lease_until)
            if lease_until is not None and lease_until < datetime.now(timezone.utc):
                await self._db.rollback()
                raise PersistenceConflict("idempotency lease expired")

        assistant = await self._assistant(execution)
        execution.status = terminal_status
        execution.completed_at = datetime.utcnow()
        assistant.status = terminal_status
        assistant.content = content
        if idem is not None:
            idem.status = "completed" if 200 <= response_status < 300 else "failed"
            idem.response_status = response_status
            idem.response_reference = response_reference
            idem.lease_until = None
        try:
            await self._db.commit()
        except Exception:
            await self._db.rollback()
            raise
        return True

    async def _locked_execution(self, execution_id: str) -> ChatExecution:
        execution = (await self._db.execute(select(ChatExecution).where(
            ChatExecution.execution_id == execution_id,
        ).with_for_update())).scalar_one_or_none()
        if execution is None:
            raise PersistenceConflict("execution does not exist")
        return execution

    async def _assistant(self, execution: ChatExecution) -> Message:
        assistant = (await self._db.execute(select(Message).where(
            Message.id == execution.assistant_message_id,
            Message.execution_id == execution.execution_id,
            Message.role == "assistant",
        ).with_for_update())).scalar_one_or_none()
        if assistant is None:
            raise PersistenceConflict("assistant message binding is invalid")
        return assistant

    @staticmethod
    def _snapshot(execution: ChatExecution) -> PersistedChatExecution:
        if execution.user_message_id is None or execution.assistant_message_id is None:
            raise PersistenceConflict("execution message binding is incomplete")
        return PersistedChatExecution(
            execution_id=execution.execution_id,
            user_message_id=execution.user_message_id,
            assistant_message_id=execution.assistant_message_id,
            status=execution.status,
        )
