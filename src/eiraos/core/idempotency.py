"""Persistent, atomic idempotency service.

State machine:

    REQUEST
       |
       v
  ATOMIC RESERVE  (INSERT … ON CONFLICT DO NOTHING / reclaim stale)
       |
       +-- completed  -> REPLAY cached response
       +-- processing (lease valid) -> 409 Conflict (in-flight)
       +-- processing (lease stale) -> RECLAIM -> EXECUTE
       +-- new                      -> EXECUTE -> complete|fail

Identity: (organization_id, user_id, key) with DB unique constraint.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import Request, HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from eiraos.domains.idempotency.models import IdempotencyRecord

DEFAULT_TTL_SECONDS = 24 * 60 * 60
LEASE_SECONDS = 120  # max time a "processing" reservation is considered live


def _body_digest(request: Request) -> str:
    raw = getattr(request.state, "cached_body", None)
    if raw is not None:
        return hashlib.sha256(raw).hexdigest()
    return ""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _resolve_context(request: Request) -> tuple[int, int]:
    org_id = getattr(request.state, "organization_id", None)
    user_id = getattr(request.state, "user_id", None)
    if org_id is None or user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Idempotency requires an authenticated tenant context.",
        )
    return int(org_id), int(user_id)


async def begin_idempotency(db: AsyncSession, request: Request, key: str) -> str:
    """Atomically reserve the idempotency key.

    Returns:
      - "processing"  -> caller should execute the side effect
      - "completed"   -> caller should replay cached response

    Raises:
      - 409 if key reused with different payload, or another worker holds a live lease
    """
    digest = _body_digest(request)
    org_id, user_id = await _resolve_context(request)
    now = _utcnow()
    expires_at = now + timedelta(seconds=DEFAULT_TTL_SECONDS)
    lease_until = now + timedelta(seconds=LEASE_SECONDS)

    # 1) Try atomic insert (wins the race when key is absent)
    stmt = (
        pg_insert(IdempotencyRecord)
        .values(
            organization_id=org_id,
            user_id=user_id,
            key=key,
            request_hash=digest,
            status="processing",
            created_at=now,
            expires_at=expires_at,
            lease_until=lease_until,
        )
        .on_conflict_do_nothing(
            index_elements=["organization_id", "user_id", "key"]
        )
        .returning(IdempotencyRecord.id)
    )
    result = await db.execute(stmt)
    inserted_id = result.scalar_one_or_none()
    if inserted_id is not None:
        await db.commit()
        return "processing"

    # 2) Key already exists — load under row lock
    existing = (
        await db.execute(
            select(IdempotencyRecord)
            .where(
                IdempotencyRecord.organization_id == org_id,
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.key == key,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()

    if existing is None:
        await db.commit()
        return await begin_idempotency(db, request, key)

    if existing.request_hash != digest:
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key was reused with a different payload.",
        )

    # Expired completed records may be reclaimed
    exp = existing.expires_at
    if exp is not None and getattr(exp, "tzinfo", None) is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if existing.status == "completed" and exp is not None and exp < now:
        existing.status = "processing"
        existing.request_hash = digest
        existing.response_status = None
        existing.response_reference = None
        existing.created_at = now
        existing.expires_at = expires_at
        existing.lease_until = lease_until
        await db.commit()
        return "processing"

    if existing.status == "completed" and existing.response_reference:
        await db.commit()
        return "completed"

    if existing.status == "failed":
        existing.status = "processing"
        existing.response_status = None
        existing.response_reference = None
        existing.lease_until = lease_until
        existing.expires_at = expires_at
        await db.commit()
        return "processing"

    # processing — check lease
    lease = existing.lease_until
    if lease is not None and getattr(lease, "tzinfo", None) is None:
        lease = lease.replace(tzinfo=timezone.utc)
    if lease is not None and lease < now:
        existing.lease_until = lease_until
        existing.status = "processing"
        await db.commit()
        return "processing"

    await db.commit()
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="A request with this idempotency key is already in progress.",
    )


async def complete_idempotency(
    db: AsyncSession,
    request: Request,
    key: str,
    response_status: int,
    response_reference: str,
) -> None:
    org_id, user_id = await _resolve_context(request)
    existing = (
        await db.execute(
            select(IdempotencyRecord)
            .where(
                IdempotencyRecord.organization_id == org_id,
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.key == key,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is None:
        return
    existing.status = "completed" if 200 <= response_status < 300 else "failed"
    existing.response_status = response_status
    existing.response_reference = response_reference
    existing.lease_until = None
    await db.commit()


async def read_cached_response(
    db: AsyncSession, request: Request, key: str
) -> str | None:
    org_id, user_id = await _resolve_context(request)
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


async def enforce_idempotency(request: Request):
    key = request.headers.get("Idempotency-Key")
    if not key:
        return None
    return key


async def record_idempotency(request: Request, response_data: dict):
    return
