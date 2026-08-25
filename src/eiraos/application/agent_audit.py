"""F6-07 durable, redacted agent lifecycle audit trail."""

from __future__ import annotations

import asyncio
from enum import StrEnum
import json
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eiraos.domains.governance.models import AgentAuditEvent


SCHEMA_VERSION = "f6-07-v1"


class AgentAuditUnavailable(RuntimeError):
    pass


class AgentEventType(StrEnum):
    RUN_STARTED = "run.started"
    PLANNER_DECISION = "planner.decision"
    AUTHORIZATION_DECISION = "authorization.decision"
    BUDGET_DECISION = "budget.decision"
    TOOL_SELECTED = "tool.selected"
    TOOL_EXECUTION_STARTED = "tool.execution.started"
    TOOL_EXECUTION_COMPLETED = "tool.execution.completed"
    TOOL_EXECUTION_FAILED = "tool.execution.failed"
    OBSERVATION_RECEIVED = "observation.received"
    RUN_TERMINATED = "run.terminated"


class AgentAuditTrail:
    def __init__(self, db: AsyncSession, *, run_id: str, organization_id: int, user_id: int, actor_context: str):
        if not run_id or len(run_id) > 64 or organization_id <= 0 or user_id <= 0 or not actor_context:
            raise ValueError("agent audit identity must be explicit")
        self._db = db
        self.run_id = run_id
        self.organization_id = organization_id
        self.user_id = user_id
        self.actor_context = _machine_value(actor_context, fallback="actor")
        self._sequence = 0
        self._lock = asyncio.Lock()

    async def record(self, event_type: AgentEventType, *, outcome: str | None = None, reason_code: str | None = None, payload: dict | None = None) -> None:
        if not isinstance(event_type, AgentEventType):
            raise AgentAuditUnavailable("unknown agent audit event type")
        safe_payload = _sanitize(payload or {})
        encoded = json.dumps(safe_payload, sort_keys=True, separators=(",", ":"))
        if len(encoded) > 8192:
            raise AgentAuditUnavailable("agent audit payload exceeds limit")
        async with self._lock:
            sequence = self._sequence + 1
            event = AgentAuditEvent(
                event_id=uuid.uuid4().hex,
                run_id=self.run_id,
                sequence=sequence,
                organization_id=self.organization_id,
                user_id=self.user_id,
                actor_context=self.actor_context,
                event_type=event_type.value,
                schema_version=SCHEMA_VERSION,
                outcome=_machine_value(outcome, fallback="outcome") if outcome else None,
                reason_code=_machine_value(reason_code, fallback="reason") if reason_code else None,
                payload_json=encoded,
            )
            try:
                self._db.add(event)
                await self._db.commit()
            except Exception as exc:
                await self._db.rollback()
                raise AgentAuditUnavailable("agent audit event could not be persisted") from exc
            self._sequence = sequence

    async def read_run(self) -> list[AgentAuditEvent]:
        return list((await self._db.execute(select(AgentAuditEvent).where(
            AgentAuditEvent.run_id == self.run_id,
            AgentAuditEvent.organization_id == self.organization_id,
        ).order_by(AgentAuditEvent.sequence))).scalars().all())


_SENSITIVE = {"authorization", "authorization_header", "token", "secret", "password", "api_key", "credential", "arguments", "result", "observation"}
_MACHINE_VALUE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def _sanitize(value, *, key="", depth=0):
    if key.lower() in _SENSITIVE or any(marker in key.lower() for marker in ("secret", "password", "token", "credential", "api_key")):
        return "[REDACTED]"
    if depth >= 6:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {str(k)[:128]: _sanitize(v, key=str(k), depth=depth + 1) for k, v in list(value.items())[:100]}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, depth=depth + 1) for item in value[:100]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:256]


def _machine_value(value, *, fallback):
    rendered = str(value)
    if _MACHINE_VALUE.fullmatch(rendered):
        return rendered
    return f"{fallback}:invalid"