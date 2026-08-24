"""Compose deterministic estimates with atomic budget reservations."""
from __future__ import annotations

from dataclasses import dataclass

from .cost_estimator import CostEstimate, CostEstimator
from .redis_reservation import RedisUsageReservation, Reservation


@dataclass(frozen=True)
class ExecutionReservation:
    estimate: CostEstimate
    primary: Reservation
    verifier: Reservation | None


class ExecutionBudget:
    def __init__(self, estimator: CostEstimator, reservations: RedisUsageReservation, *, ttl_seconds: int = 3600) -> None:
        self.estimator = estimator
        self.reservations = reservations
        self.ttl_seconds = ttl_seconds

    async def reserve(self, *, user_id: int, organization_id: int, prompt: str, verify: bool, user_limit: int, organization_limit: int) -> ExecutionReservation:
        estimate = self.estimator.estimate(prompt=prompt, verify=verify)
        total = estimate.total_tokens
        if total > organization_limit or total > user_limit:
            raise RuntimeError("execution budget exceeded")
        primary = await self.reservations.reserve(f"user:{user_id}:budget", estimate.primary_tokens, user_limit, self.ttl_seconds)
        verifier = None
        try:
            if verify:
                verifier = await self.reservations.reserve(f"user:{user_id}:verification", estimate.verifier_tokens, user_limit, self.ttl_seconds)
        except Exception:
            await self.reservations.release(primary)
            raise
        return ExecutionReservation(estimate=estimate, primary=primary, verifier=verifier)

    async def release(self, reservation: ExecutionReservation) -> None:
        if reservation.verifier is not None:
            await self.reservations.release(reservation.verifier)
        await self.reservations.release(reservation.primary)
