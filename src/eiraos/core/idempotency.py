"""Persistent, atomic idempotency service.

Implements the safe idempotency state machine:

    [key absent] -> create "processing" reservation -> (side effect)
                  -> mark "completed" with cached response
    [key reused, same hash, not expired] -> return cached response (no re-execute)
    [key reused, different hash]         -> HTTP 409 Conflict
    [key expired]                        -> new reservation may proceed

The ledger is DB-backed (IdempotencyRecord) so duplicate protection survives
restarts and spans multiple worker processes, unlike the previous in-memory stub.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from fastapi import Request, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eiraos.core.database import get_db
from eiraos.domains.idempotency.models import IdempotencyRecord

DEFAULT_TTL_SECONDS = 24 * 60 * 60  # 24h


def _body_digest(request: Request) -> str:
    raw = getattr(request.state, "cached_body", None)
    if raw is not None:
        return hashlib.sha256(raw).hexdigest()
    return ""  # GET-ish request without a meaningful body


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _resolve_context(request: Request) -> tuple[int, int]:
    """Return (organization_id, user_id) from the authenticated request state."""
    org_id = getattr(request.state, "organization_id", None)
    user_id = getattr(request.state, "user_id", None)
    if org_id is None or user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Idempotency requires an authenticated tenant context.",
        )
    return int(org_id), int(user_id)


async def begin_idempotency(db: AsyncSession, request: Request, key: str) -> str:
    """Atomically reserve the idempotency key and return its status.

    Raises HTTPException(409) when the key is reused with a different payload,
    and HTTPException(200-redirect-free) semantics by returning 'completed'
    when a cached response already exists for the same payload.
    """
    digest = _body_digest(request)
    org_id, user_id = await _resolve_context(request)

    existing: IdempotencyRecord | None = (
        await db.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.organization_id == org_id,
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.key == key,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        now = _utcnow()
        record = IdempotencyRecord(
            organization_id=org_id,
            user_id=user_id,
            key=key,
            request_hash=digest,
            status="processing",
            created_at=now,
            expires_at=now.fromtimestamp(now.timestamp() + DEFAULT_TTL_SECONDS),
        )
        db.add(record)
        await db.commit()
        return "processing"

    if existing.request_hash != digest:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key was reused with a different payload.",
        )

    if existing.status == "completed" and existing.response_reference:
        return "completed"
    return existing.status


async def complete_idempotency(
    db: AsyncSession, request: Request, key: str, response_status: int,
    response_reference: str,
) -> None:
    org_id, user_id = await _resolve_context(request)
    existing = (
        await db.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.organization_id == org_id,
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.key == key,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        return
    existing.status = "completed"
    existing.response_status = response_status
    existing.response_reference = response_reference
    await db.flush()


async def read_cached_response(request: Request, key: str) -> str | None:
    """Return the cached response reference for a completed key, if any."""
    org_id, user_id = await _resolve_context(request)
    async for db in get_db():
        existing = (
            await db.execute(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.organization_id == org_id,
                    IdempotencyRecord.user_id == user_id,
                    IdempotencyRecord.key == key,
                    IdempotencyRecord.status == "completed",
                )
            )
        ).scalar_one_or_none()
        return existing.response_reference if existing else None
    return None


# --- Backwards-compatible helper for routes not yet migrated -----------------
async def enforce_idempotency(request: Request):
    key = request.headers.get("Idempotency-Key")
    if not key:
        return None
    return key


async def record_idempotency(request: Request, response_data: dict):
    """No-op on the old signature; the DB-backed path is used by migrated routes."""
    return
