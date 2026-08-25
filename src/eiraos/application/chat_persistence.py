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
from eiraos.application.chat_recovery import FailureCode, failure_policy


TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


class PersistenceConflict(RuntimeError):
    """Raised when durable state no longer permits the requested transition."""


class PersistenceUnavailable(RuntimeError):
    """Raised when an atomic persistence transition could not be committed."""


class RetryLimitExceeded(PersistenceConflict):
    """Raised when a durable execution has consumed its attempt budget."""


@dataclass(frozen=True)
class PersistedChatExecution:
    execution_id: str
    user_message_id: int
    assistant_message_id: int
    status: str


def execution_identity(
    *, organization_id: int, user_id: int, idempotency_key: str | None,
    idempotency_record_id: int | None = None,
) -> str:
    """Return a replay-stable identity when idempotency is present."""
    if not idempotency_key:
        return uuid.uuid4().hex
    material = f"{organization_id}:{user_id}:{idempotency_key}:{idempotency_record_id or ''}".encode()
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
        recover: bool = False,
        lease_token: str | None = None,
        max_attempts: int = 3,
    ) -> PersistedChatExecution:
        existing = (await self._execute(select(ChatExecution).where(
            ChatExecution.execution_id == execution_id,
        ).with_for_update())).scalar_one_or_none()
        if existing is not None:
            if (
                existing.organization_id != organization_id
                or existing.user_id != user_id
                or existing.conversation_id != conversation_id
                or existing.bot_id != bot_id
                or existing.idempotency_record_id != idempotency_record_id
                or existing.provider != provider
                or existing.model != model
            ):
                raise PersistenceConflict("execution identity is bound to another scope")
            if not recover:
                await self._db.rollback()
                raise PersistenceConflict("existing execution requires an owned recovery lease")
            await self._assert_recovery_owner(existing, lease_token)
            assistant = await self._assistant(existing)
            if existing.attempt_count >= existing.max_attempts:
                existing.status = "failed"
                existing.last_failure_code = FailureCode.RETRY_EXHAUSTED.value
                existing.failure_retryable = False
                existing.partial_response = bool(assistant.content)
                existing.completed_at = datetime.utcnow()
                assistant.status = "failed"
                await self._commit_or_unavailable()
                raise RetryLimitExceeded("execution retry limit was reached")
            if existing.status in {"prepared", "streaming"}:
                existing.last_failure_code = FailureCode.PROCESS_CRASH.value
                existing.failure_retryable = True
            elif existing.status not in {"failed", "cancelled"}:
                await self._db.rollback()
                raise PersistenceConflict("execution state is not recoverable")
            elif not existing.failure_retryable:
                await self._db.rollback()
                raise PersistenceConflict("execution failure is not retryable")
            assistant.content = ""
            assistant.status = "pending"
            existing.status = "prepared"
            existing.attempt_count += 1
            existing.recovered_at = datetime.utcnow()
            existing.completed_at = None
            existing.partial_response = False
            usage = (await self._execute(select(ProviderUsageRecord).where(
                ProviderUsageRecord.chat_execution_id == existing.id,
            ).with_for_update())).scalar_one_or_none()
            if usage is None:
                await self._db.rollback()
                raise PersistenceConflict("execution usage binding is invalid")
            usage.total_tokens += estimated_tokens
            usage.estimated_cost += Decimal(str(estimated_cost))
            await self._commit_or_unavailable()
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
            attempt_count=1,
            max_attempts=max_attempts,
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
            raise PersistenceUnavailable("chat execution preparation could not be flushed")
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
            raise PersistenceUnavailable("chat execution preparation could not be committed")
        return self._snapshot(execution)

    async def mark_streaming(self, execution_id: str) -> bool:
        execution = await self._locked_execution(execution_id)
        if execution.status in TERMINAL_STATUSES:
            return False
        assistant = await self._assistant(execution)
        execution.status = "streaming"
        assistant.status = "streaming"
        await self._commit_or_unavailable()
        return True

    async def assert_recovery_allowed(
        self,
        *,
        execution_id: str,
        idempotency_record_id: int,
        lease_token: str | None,
    ) -> None:
        """Reject exhausted/non-retryable recovery before budget reservation."""
        execution = (await self._execute(select(ChatExecution).where(
            ChatExecution.execution_id == execution_id,
        ).with_for_update())).scalar_one_or_none()
        if execution is None:
            await self._db.rollback()
            return
        if execution.idempotency_record_id != idempotency_record_id:
            await self._db.rollback()
            raise PersistenceConflict("recovery identity is bound to another record")
        idem = await self._assert_recovery_owner(execution, lease_token)
        assistant = await self._assistant(execution)
        if execution.attempt_count >= execution.max_attempts:
            execution.status = "failed"
            execution.last_failure_code = FailureCode.RETRY_EXHAUSTED.value
            execution.failure_retryable = False
            execution.partial_response = bool(assistant.content)
            execution.completed_at = datetime.utcnow()
            assistant.status = "failed"
            idem.status = "failed"
            idem.response_status = failure_policy(FailureCode.RETRY_EXHAUSTED).response_status
            idem.response_reference = "failed"
            idem.lease_until = None
            await self._commit_or_unavailable()
            raise RetryLimitExceeded("execution retry limit was reached")
        if execution.status not in {"prepared", "streaming", "failed", "cancelled"}:
            await self._db.rollback()
            raise PersistenceConflict("execution state is not recoverable")
        if execution.status in {"failed", "cancelled"} and not execution.failure_retryable:
            await self._db.rollback()
            raise PersistenceConflict("execution failure is not retryable")
        await self._db.rollback()

    async def finalize(
        self,
        *,
        execution_id: str,
        terminal_status: str,
        content: str,
        response_status: int,
        response_reference: str,
        lease_token: str | None,
        failure_code: FailureCode | None = None,
    ) -> bool:
        if terminal_status not in TERMINAL_STATUSES:
            raise ValueError("terminal_status must be completed, failed or cancelled")
        execution = await self._locked_execution(execution_id)
        if execution.status in TERMINAL_STATUSES:
            await self._db.rollback()
            return False
        if terminal_status != "completed" and failure_code is None:
            await self._db.rollback()
            raise ValueError("terminal failures require a failure_code")

        idem = None
        if execution.idempotency_record_id is not None:
            idem = (await self._execute(select(IdempotencyRecord).where(
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
        execution.partial_response = terminal_status != "completed" and bool(content)
        if failure_code is not None:
            execution.last_failure_code = failure_code.value
            policy = failure_policy(failure_code)
            execution.failure_retryable = policy.retryable
            response_status = policy.response_status
        elif terminal_status == "completed":
            execution.failure_retryable = False
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
            raise PersistenceUnavailable("chat execution finalization could not be committed")
        return True

    async def _assert_recovery_owner(
        self, execution: ChatExecution, lease_token: str | None,
    ) -> IdempotencyRecord:
        if execution.idempotency_record_id is None or lease_token is None:
            await self._db.rollback()
            raise PersistenceConflict("recovery requires idempotency ownership")
        idem = (await self._execute(select(IdempotencyRecord).where(
            IdempotencyRecord.id == execution.idempotency_record_id,
        ).with_for_update())).scalar_one_or_none()
        lease_until = _as_utc(idem.lease_until) if idem is not None else None
        if (
            idem is None
            or idem.status != "processing"
            or idem.lease_token != lease_token
            or (lease_until is not None and lease_until < datetime.now(timezone.utc))
        ):
            await self._db.rollback()
            raise PersistenceConflict("recovery lease ownership was lost")
        return idem

    async def _commit_or_unavailable(self) -> None:
        try:
            await self._db.commit()
        except Exception as exc:
            await self._db.rollback()
            raise PersistenceUnavailable("chat persistence is unavailable") from exc

    async def _execute(self, statement):
        try:
            return await self._db.execute(statement)
        except Exception as exc:
            await self._db.rollback()
            raise PersistenceUnavailable("chat persistence query failed") from exc

    async def _locked_execution(self, execution_id: str) -> ChatExecution:
        execution = (await self._execute(select(ChatExecution).where(
            ChatExecution.execution_id == execution_id,
        ).with_for_update())).scalar_one_or_none()
        if execution is None:
            raise PersistenceConflict("execution does not exist")
        return execution

    async def _assistant(self, execution: ChatExecution) -> Message:
        assistant = (await self._execute(select(Message).where(
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
