"""F6-05 bounded agent loop orchestration."""

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True, slots=True)
class LoopStep:
    tool: str
    capability: str
    arguments: dict


@dataclass(frozen=True, slots=True)
class LoopOutcome:
    status: str
    observation: Optional[object] = None
    reason_code: Optional[str] = None
    steps: int = 0


def run_agent_loop(
    planner: Callable[[object, Optional[object]], Optional[LoopStep]],
    authorize: Callable[[LoopStep], object],
    budget: object,
    execute: Callable[[LoopStep], object],
    conversation: object,
    *,
    max_steps: int = 1,
) -> LoopOutcome:
    """Run planner -> policy -> execution -> observation until terminal."""
    if max_steps < 1:
        return LoopOutcome("DENIED", reason_code="INVALID_MAX_STEPS")

    observation = None
    for step_number in range(1, max_steps + 1):
        step = planner(conversation, observation)
        if step is None:
            return LoopOutcome("COMPLETE", observation, steps=step_number - 1)

        decision = authorize(step)
        if not getattr(decision, "allowed", False):
            return LoopOutcome("DENIED", observation, getattr(decision, "reason_code", "UNAUTHORIZED"), step_number)

        budget_decision = budget.consume()
        if not budget_decision.allowed:
            return LoopOutcome("BUDGET_EXHAUSTED", observation, budget_decision.reason_code, step_number)

        observation = execute(step)

    return LoopOutcome("STEP_LIMIT_REACHED", observation, "MAX_STEPS_REACHED", max_steps)
