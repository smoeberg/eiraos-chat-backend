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
