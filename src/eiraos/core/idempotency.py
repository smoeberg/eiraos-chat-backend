"""Persistent, atomic idempotency service with lease fencing."""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Request, HTTPException, status
from sqlalchemy import select, delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from eiraos.domains.idempotency.models import IdempotencyRecord

DEFAULT_TTL_SECONDS = 24 * 60 * 60
LEASE_SECONDS = 120
LEASE_RENEWAL_SECONDS = 60


@dataclass(frozen=True)
class IdempotencyOutcome:
    status: str
    lease_token: str | None = None
    record_id: int | None = None
    is_recovery: bool = False

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.status == other
        return super().__eq__(other)


def _body_digest(request: Request) -> str:
    raw = getattr(request.state, "cached_body", None)
    if raw is not None:
        return hashlib.sha256(raw).hexdigest()
    return ""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_token() -> str:
    return uuid.uuid4().hex


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def _resolve_context(request: Request) -> tuple[int, int]:
    org_id = getattr(request.state, "organization_id", None)
    user_id = getattr(request.state, "user_id", None)
    if org_id is None or user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Idempotency requires an authenticated tenant context.")
    return int(org_id), int(user_id)


def resolve_idempotency_key(request: Request, body_key: str | None = None) -> str | None:
    header_key = (request.headers.get("Idempotency-Key") or "").strip() or None
    body = (body_key or "").strip() or None
    if header_key and body and header_key != body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Idempotency-Key header and body field mismatch.")
    return header_key or body


async def begin_idempotency(db: AsyncSession, request: Request, key: str, *, _attempts: int = 0) -> IdempotencyOutcome:
    digest = _body_digest(request)
    org_id, user_id = await _resolve_context(request)
    now = _utcnow()
    expires_at = now + timedelta(seconds=DEFAULT_TTL_SECONDS)
    lease_until = now + timedelta(seconds=LEASE_SECONDS)
    token = _new_token()
    stmt = (
        pg_insert(IdempotencyRecord)
        .values(organization_id=org_id, user_id=user_id, key=key, request_hash=digest, status="processing",
                created_at=now, expires_at=expires_at, lease_until=lease_until, lease_token=token)
        .on_conflict_do_nothing(index_elements=["organization_id", "user_id", "key"])
        .returning(IdempotencyRecord.id)
    )
    result = await db.execute(stmt)
    inserted_id = result.scalar_one_or_none()
    if inserted_id is not None:
        await db.commit()
        return IdempotencyOutcome("processing", token, int(inserted_id), False)
    existing = (await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.organization_id == org_id, IdempotencyRecord.user_id == user_id,
        IdempotencyRecord.key == key).with_for_update())).scalar_one_or_none()
    if existing is None:
        await db.commit()
        if _attempts >= 2:
            raise HTTPException(status_code=503, detail="Idempotency reservation failed after retries.")
        return await begin_idempotency(db, request, key, _attempts=_attempts + 1)
    exp = _as_utc(existing.expires_at)
    if existing.status == "completed" and exp is not None and exp < now:
        await db.delete(existing)
        await db.commit()
        if _attempts >= 2:
            raise HTTPException(status_code=503, detail="Idempotency renewal failed after retries.")
        return await begin_idempotency(db, request, key, _attempts=_attempts + 1)
    if existing.request_hash != digest:
        await db.commit()
        raise HTTPException(status_code=409, detail="Idempotency key was reused with a different payload.")
    if existing.status == "completed" and existing.response_reference:
        await db.commit()
        return IdempotencyOutcome("completed", None, existing.id, False)
    if existing.status == "failed":
        existing.status = "processing"
        existing.response_status = existing.response_reference = None
        existing.lease_until, existing.expires_at, existing.lease_token = lease_until, expires_at, token
        await db.commit()
        return IdempotencyOutcome("processing", token, existing.id, True)
    lease = _as_utc(existing.lease_until)
    if lease is not None and lease < now:
        existing.lease_until, existing.lease_token, existing.status = lease_until, token, "processing"
        await db.commit()
        return IdempotencyOutcome("processing", token, existing.id, True)
    await db.commit()
    raise HTTPException(status_code=409, detail="A request with this idempotency key is already in progress.")


async def renew_idempotency_lease(db: AsyncSession, request: Request, key: str, lease_token: str) -> bool:
    """Atomically extend the lease only while this caller still owns it."""
    org_id, user_id = await _resolve_context(request)
    now = _utcnow()
    result = await db.execute(update(IdempotencyRecord).where(
        IdempotencyRecord.organization_id == org_id,
        IdempotencyRecord.user_id == user_id,
        IdempotencyRecord.key == key,
        IdempotencyRecord.status == "processing",
        IdempotencyRecord.lease_token == lease_token,
    ).values(lease_until=now + timedelta(seconds=LEASE_SECONDS)))
    await db.commit()
    return result.rowcount == 1


async def complete_idempotency(db: AsyncSession, request: Request, key: str, response_status: int,
                               response_reference: str, lease_token: str | None = None) -> bool:
    org_id, user_id = await _resolve_context(request)
    now = _utcnow()
    existing = (await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.organization_id == org_id, IdempotencyRecord.user_id == user_id,
        IdempotencyRecord.key == key).with_for_update())).scalar_one_or_none()
    if existing is None:
        return False
    if lease_token is not None:
        lease = _as_utc(existing.lease_until)
        if existing.lease_token not in (None, lease_token) or (lease is not None and lease < now):
            await db.commit()
            return False
    existing.status = "completed" if 200 <= response_status < 300 else "failed"
    existing.response_status = response_status
    existing.response_reference = response_reference
    existing.lease_until = None
    await db.commit()
    return True


async def read_cached_response(db: AsyncSession, request: Request, key: str) -> str | None:
    org_id, user_id = await _resolve_context(request)
    existing = (await db.execute(select(IdempotencyRecord).where(
        IdempotencyRecord.organization_id == org_id, IdempotencyRecord.user_id == user_id,
        IdempotencyRecord.key == key, IdempotencyRecord.status == "completed"))).scalar_one_or_none()
    return existing.response_reference if existing else None


async def cleanup_expired_records(db: AsyncSession, limit: int = 1000) -> int:
    now = _utcnow()
    result = await db.execute(delete(IdempotencyRecord).where(
        IdempotencyRecord.expires_at.is_not(None), IdempotencyRecord.expires_at < now,
        IdempotencyRecord.status.in_(["completed", "failed"])).execution_options(synchronize_session=False))
    await db.commit()
    return int(result.rowcount or 0)


async def enforce_idempotency(request: Request):
    return resolve_idempotency_key(request)


async def record_idempotency(request: Request, response_data: dict):
    return
