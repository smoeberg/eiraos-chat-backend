"""Compose deterministic estimates with atomic budget reservations."""
from __future__ import annotations

from dataclasses import dataclass

from .cost_estimator import CostEstimate, CostEstimator
from .redis_reservation import (
    BudgetReservationDenied,
    RedisUsageReservation,
    TenantReservation,
)


@dataclass(frozen=True)
class ExecutionReservation:
    estimate: CostEstimate
    tenant: TenantReservation

    @property
    def total_reserved_tokens(self) -> int:
        return self.estimate.total_tokens


class ExecutionBudget:
    def __init__(self, estimator: CostEstimator, reservations: RedisUsageReservation, *, ttl_seconds: int = 3600) -> None:
        self.estimator = estimator
        self.reservations = reservations
        self.ttl_seconds = ttl_seconds

    async def reserve(self, *, reservation_id: str, user_id: int, organization_id: int, prompt: str, verify: bool, user_limit: int, organization_limit: int) -> ExecutionReservation:
        estimate = self.estimator.estimate(prompt=prompt, verify=verify)
        total = estimate.total_tokens
        if total > organization_limit or total > user_limit:
            raise BudgetReservationDenied("execution token budget exceeded")
        tag = f"{{{organization_id}}}"
        tenant = await self.reservations.reserve_tenant(
            reservation_id=reservation_id,
            user_key=f"budget:{tag}:user:{user_id}:tokens",
            organization_key=f"budget:{tag}:organization:tokens",
            amount=total,
            user_limit=user_limit,
            organization_limit=organization_limit,
            ttl_seconds=self.ttl_seconds,
        )
        return ExecutionReservation(estimate=estimate, tenant=tenant)
