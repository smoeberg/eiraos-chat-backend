"""Core F2-02 usage and budget enforcement primitives.

This module is deliberately provider-agnostic. It provides an atomic in-memory
reservation primitive for the first implementation step; production storage
must be backed by an atomic Redis reservation layer and durable usage records.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class UsageBudgetError(RuntimeError):
    """Base error for usage/budget enforcement failures."""


class BudgetUnavailable(UsageBudgetError):
    """Raised when budget state cannot be safely determined."""


class BudgetExceeded(UsageBudgetError):
    """Raised when a configured budget would be exceeded."""


@dataclass
class UsageBudgetReservation:
    user_id: int
    organization_id: int
    estimated_cost: float
    verification_estimated_cost: float = 0.0
    total_reserved_cost: float = 0.0


class UsageBudgetGate:
    """Fail-closed reservation gate for user/org/execution budgets."""

    def __init__(
        self,
        *,
        user_remaining: float | None = None,
        organization_remaining: float | None = None,
        max_execution_cost: float | None = None,
        backend_available: bool = True,
    ) -> None:
        self._user_remaining = user_remaining
        self._organization_remaining = organization_remaining
        self._max_execution_cost = max_execution_cost
        self._backend_available = backend_available

    @classmethod
    def for_test(cls, **kwargs: Any) -> "UsageBudgetGate":
        return cls(**kwargs)

    def _required_cost(self, estimated_cost: float, verification_estimated_cost: float = 0.0) -> float:
        if estimated_cost < 0 or verification_estimated_cost < 0:
            raise BudgetExceeded("Estimated cost cannot be negative.")
        return estimated_cost + verification_estimated_cost

    def _validate(self, *, estimated_cost: float, verification_estimated_cost: float) -> float:
        if not self._backend_available:
            raise BudgetUnavailable("Usage budget state is unavailable.")
        required = self._required_cost(estimated_cost, verification_estimated_cost)
        if self._max_execution_cost is not None and required > self._max_execution_cost:
            raise BudgetExceeded("Execution budget exceeded.")
        if self._user_remaining is not None and required > self._user_remaining:
            raise BudgetExceeded("User quota exceeded.")
        if self._organization_remaining is not None and required > self._organization_remaining:
            raise BudgetExceeded("Organization budget exceeded.")
        return required

    def try_reserve(
        self,
        *,
        user_id: int,
        organization_id: int,
        estimated_cost: float,
        verification_estimated_cost: float = 0.0,
    ) -> bool:
        """Attempt an atomic reservation; return False when it cannot be made."""
        try:
            required = self._validate(
                estimated_cost=estimated_cost,
                verification_estimated_cost=verification_estimated_cost,
            )
        except UsageBudgetError:
            return False

        if self._user_remaining is not None:
            self._user_remaining -= required
        if self._organization_remaining is not None:
            self._organization_remaining -= required
        return True

    def reserve_or_raise(
        self,
        *,
        user_id: int,
        organization_id: int,
        estimated_cost: float,
        verification_estimated_cost: float = 0.0,
        provider_call: Any | None = None,
    ) -> UsageBudgetReservation:
        """Reserve budget and return a reservation before provider execution."""
        required = self._validate(
            estimated_cost=estimated_cost,
            verification_estimated_cost=verification_estimated_cost,
        )
        if self._user_remaining is not None:
            self._user_remaining -= required
        if self._organization_remaining is not None:
            self._organization_remaining -= required
        return UsageBudgetReservation(
            user_id=user_id,
            organization_id=organization_id,
            estimated_cost=estimated_cost,
            verification_estimated_cost=verification_estimated_cost,
            total_reserved_cost=required,
        )
