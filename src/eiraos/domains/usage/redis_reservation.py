"""Atomic Redis reservation primitive for F2-02.

The adapter deliberately exposes no provider credentials or response data.
Production wiring must supply a real Redis client; unavailable Redis is a
hard failure rather than an in-memory fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class BudgetBackendUnavailable(RuntimeError):
    """Budget state cannot be safely evaluated."""


class BudgetReservationDenied(RuntimeError):
    """Requested reservation exceeds an applicable budget."""


@dataclass(frozen=True)
class Reservation:
    key: str
    amount: int


@dataclass(frozen=True)
class TenantReservation:
    reservation_id: str
    marker_key: str
    user: Reservation
    organization: Reservation
    replayed: bool = False


class RedisUsageReservation:
    """Small boundary around an atomic Redis reservation operation."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    async def reserve(self, key: str, amount: int, limit: int, ttl_seconds: int) -> Reservation:
        if amount < 0 or limit < 0:
            raise ValueError("amount and limit must be non-negative")
        if not key:
            raise ValueError("reservation key is required")
        if self._redis is None:
            raise BudgetBackendUnavailable("budget backend unavailable")

        script = """
        local current = redis.call('GET', KEYS[1])
        current = tonumber(current) or 0
        local requested = tonumber(ARGV[1])
        local limit = tonumber(ARGV[2])
        if current + requested > limit then
            return 0
        end
        redis.call('INCRBY', KEYS[1], requested)
        redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
        return 1
        """
        try:
            result = await self._redis.eval(script, 1, key, amount, limit, ttl_seconds)
        except Exception as exc:
            raise BudgetBackendUnavailable("budget backend unavailable") from exc

        if int(result) != 1:
            raise BudgetReservationDenied("budget reservation denied")
        return Reservation(key=key, amount=amount)

    async def release(self, reservation: Reservation) -> None:
        if self._redis is None:
            raise BudgetBackendUnavailable("budget backend unavailable")
        try:
            await self._redis.decrby(reservation.key, reservation.amount)
        except Exception as exc:
            raise BudgetBackendUnavailable("budget backend unavailable") from exc

    async def reserve_tenant(
        self,
        *,
        reservation_id: str,
        user_key: str,
        organization_key: str,
        amount: int,
        user_limit: int,
        organization_limit: int,
        ttl_seconds: int,
    ) -> TenantReservation:
        if not reservation_id or not user_key or not organization_key:
            raise ValueError("tenant reservation identity is required")
        if min(amount, user_limit, organization_limit, ttl_seconds) <= 0:
            raise ValueError("tenant reservation values must be positive")
        if self._redis is None:
            raise BudgetBackendUnavailable("budget backend unavailable")
        marker_key = f"{organization_key}:reservation:{reservation_id}"
        identity = f"{user_key}|{organization_key}|{amount}"
        script = """
        local existing = redis.call('GET', KEYS[1])
        if existing then
            if existing == ARGV[5] then return 2 else return -1 end
        end
        local user_current = tonumber(redis.call('GET', KEYS[2])) or 0
        local org_current = tonumber(redis.call('GET', KEYS[3])) or 0
        local amount = tonumber(ARGV[1])
        if user_current + amount > tonumber(ARGV[2]) then return 0 end
        if org_current + amount > tonumber(ARGV[3]) then return 0 end
        redis.call('INCRBY', KEYS[2], amount)
        redis.call('INCRBY', KEYS[3], amount)
        redis.call('SET', KEYS[1], ARGV[5], 'EX', tonumber(ARGV[4]))
        redis.call('EXPIRE', KEYS[2], tonumber(ARGV[4]))
        redis.call('EXPIRE', KEYS[3], tonumber(ARGV[4]))
        return 1
        """
        try:
            result = int(await self._redis.eval(
                script, 3, marker_key, user_key, organization_key,
                amount, user_limit, organization_limit, ttl_seconds, identity,
            ))
        except Exception as exc:
            raise BudgetBackendUnavailable("budget backend unavailable") from exc
        if result == 0:
            raise BudgetReservationDenied("tenant token budget exceeded")
        if result not in {1, 2}:
            raise BudgetReservationDenied("reservation identity conflict")
        return TenantReservation(
            reservation_id=reservation_id,
            marker_key=marker_key,
            user=Reservation(user_key, amount),
            organization=Reservation(organization_key, amount),
            replayed=result == 2,
        )

    async def release_tenant(self, reservation: TenantReservation) -> None:
        """Release only a newly-created reservation, atomically and idempotently."""
        if reservation.replayed:
            return
        identity = (
            f"{reservation.user.key}|{reservation.organization.key}|"
            f"{reservation.user.amount}"
        )
        script = """
        if redis.call('GET', KEYS[1]) ~= ARGV[2] then return 0 end
        local amount = tonumber(ARGV[1])
        local user_current = tonumber(redis.call('GET', KEYS[2])) or 0
        local org_current = tonumber(redis.call('GET', KEYS[3])) or 0
        redis.call('SET', KEYS[2], math.max(0, user_current - amount), 'KEEPTTL')
        redis.call('SET', KEYS[3], math.max(0, org_current - amount), 'KEEPTTL')
        redis.call('DEL', KEYS[1])
        return 1
        """
        try:
            await self._redis.eval(
                script, 3, reservation.marker_key, reservation.user.key,
                reservation.organization.key, reservation.user.amount, identity,
            )
        except Exception as exc:
            raise BudgetBackendUnavailable("budget backend unavailable") from exc

    async def settle_tenant(
        self, reservation: TenantReservation, *, actual_amount: int,
    ) -> bool:
        """Reconcile both counters once; return False for an identical replay."""
        if actual_amount < 0:
            raise ValueError("actual usage cannot be negative")
        identity = (
            f"{reservation.user.key}|{reservation.organization.key}|"
            f"{reservation.user.amount}"
        )
        settlement_key = f"{reservation.marker_key}:settled"
        script = """
        if redis.call('GET', KEYS[1]) ~= ARGV[3] then return -1 end
        local existing = redis.call('GET', KEYS[2])
        if existing then
            if existing == ARGV[2] then return 0 else return -2 end
        end
        local ttl = redis.call('PTTL', KEYS[1])
        if ttl <= 0 then return -1 end
        local delta = tonumber(ARGV[2]) - tonumber(ARGV[1])
        redis.call('INCRBY', KEYS[3], delta)
        redis.call('INCRBY', KEYS[4], delta)
        redis.call('SET', KEYS[2], ARGV[2], 'PX', ttl)
        return 1
        """
        try:
            result = int(await self._redis.eval(
                script, 4, reservation.marker_key, settlement_key,
                reservation.user.key, reservation.organization.key,
                reservation.user.amount, actual_amount, identity,
            ))
        except Exception as exc:
            raise BudgetBackendUnavailable("budget backend unavailable") from exc
        if result < 0:
            raise BudgetReservationDenied("budget settlement identity conflict")
        return result == 1
