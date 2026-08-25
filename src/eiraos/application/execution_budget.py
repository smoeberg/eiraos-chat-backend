"""F6-04 bounded execution budget."""

from dataclasses import dataclass
from threading import Lock
from time import monotonic


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    allowed: bool
    reason_code: str
    remaining_executions: int


class ExecutionBudget:
    def __init__(self, max_executions: int, timeout_seconds: float, *, clock=monotonic):
        if max_executions < 0 or timeout_seconds <= 0:
            raise ValueError("invalid execution budget")
        self._remaining = max_executions
        self._deadline = clock() + timeout_seconds
        self._clock = clock
        self._lock = Lock()

    def consume(self) -> BudgetDecision:
        with self._lock:
            if self._clock() >= self._deadline:
                return BudgetDecision(False, "TIME_BUDGET_EXHAUSTED", self._remaining)
            if self._remaining <= 0:
                return BudgetDecision(False, "EXECUTION_BUDGET_EXHAUSTED", 0)
            self._remaining -= 1
            return BudgetDecision(True, "BUDGET_GRANTED", self._remaining)

    @property
    def remaining_executions(self) -> int:
        with self._lock:
            return self._remaining
