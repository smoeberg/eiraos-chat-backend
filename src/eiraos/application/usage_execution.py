"""F2-03 provider execution budget boundary.

This layer owns the fail-closed decision immediately before provider execution.
It deliberately does not know about HTTP, database models, or provider secrets.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from eiraos.core.usage_budget import BudgetExceeded, UsageBudgetGate, UsageBudgetReservation
from eiraos.domains.usage.cost_estimator import CostEstimate, CostEstimator


@dataclass(frozen=True)
class BudgetedExecution:
    estimate: CostEstimate
    reservation: UsageBudgetReservation


class ProviderExecutionBudget:
    """Deterministic estimate + fail-closed reservation before provider use."""

    def __init__(
        self,
        *,
        estimator: CostEstimator,
        gate_factory: Callable[[], UsageBudgetGate],
    ) -> None:
        self._estimator = estimator
        self._gate_factory = gate_factory

    def reserve(
        self,
        *,
        user_id: int,
        organization_id: int,
        prompt: str,
        verify: bool,
    ) -> BudgetedExecution:
        estimate = self._estimator.estimate(prompt=prompt, verify=verify)
        gate = self._gate_factory()
        try:
            reservation = gate.reserve_or_raise(
                user_id=user_id,
                organization_id=organization_id,
                estimated_cost=float(estimate.primary_tokens),
                verification_estimated_cost=float(estimate.verifier_tokens),
            )
        except BudgetExceeded:
            raise
        return BudgetedExecution(estimate=estimate, reservation=reservation)
