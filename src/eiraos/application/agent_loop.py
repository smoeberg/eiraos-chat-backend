"""F6-05/F6-06 bounded agent loop orchestration."""

import asyncio
import hashlib
import inspect
import json
import math
from dataclasses import dataclass
from time import monotonic
from types import MappingProxyType
from typing import Awaitable, Callable, Mapping, Optional

from eiraos.application.agent_audit import AgentEventType


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
    termination_context: Mapping[str, float | int] | None = None


@dataclass(frozen=True, slots=True)
class AgentRunLimits:
    max_depth: int
    timeout_seconds: float
    tool_timeout_seconds: float

    def __post_init__(self) -> None:
        if not isinstance(self.max_depth, int) or isinstance(self.max_depth, bool) or self.max_depth < 1:
            raise ValueError("maximum depth must be a positive integer")
        if not _finite_positive(self.timeout_seconds):
            raise ValueError("run timeout must be finite and positive")
        if not _finite_positive(self.tool_timeout_seconds):
            raise ValueError("tool timeout must be finite and positive")
        if self.tool_timeout_seconds > self.timeout_seconds:
            raise ValueError("tool timeout cannot exceed run timeout")


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


async def run_agent_loop_async(
    planner: Callable[[object, Optional[object]], LoopStep | None | Awaitable[LoopStep | None]],
    authorize: Callable[[LoopStep], object | Awaitable[object]],
    budget: object,
    execute: Callable[[LoopStep], Awaitable[object]],
    conversation: object,
    *,
    limits: AgentRunLimits,
    audit: object,
    clock=monotonic,
) -> LoopOutcome:
    """Run with immutable bounds and a required durable audit writer."""
    started = clock()
    deadline = started + limits.timeout_seconds
    await audit.record(AgentEventType.RUN_STARTED, payload={
        "max_depth": limits.max_depth,
        "timeout_seconds": limits.timeout_seconds,
        "tool_timeout_seconds": limits.tool_timeout_seconds,
    })

    async def finish(outcome: LoopOutcome) -> LoopOutcome:
        await audit.record(
            AgentEventType.RUN_TERMINATED,
            outcome=outcome.status,
            reason_code=outcome.reason_code,
            payload=dict(outcome.termination_context or {}),
        )
        return outcome

    if not _is_async_callable(execute):
        return await finish(_terminal("DENIED", "NON_CANCELLABLE_EXECUTOR", 0, limits, started, deadline))
    observation = None
    depth = 0
    while depth < limits.max_depth:
        if clock() >= deadline:
            return await finish(_terminal("TIMEOUT", "RUN_DEADLINE_EXCEEDED", depth, limits, started, deadline))
        try:
            step = await _invoke_within_deadline(
                planner, conversation, observation, deadline=deadline, clock=clock,
            )
        except TimeoutError:
            await audit.record(AgentEventType.PLANNER_DECISION, outcome="timeout", reason_code="RUN_DEADLINE_EXCEEDED", payload={"depth": depth})
            return await finish(_terminal("TIMEOUT", "RUN_DEADLINE_EXCEEDED", depth, limits, started, deadline))
        except Exception:
            await audit.record(AgentEventType.PLANNER_DECISION, outcome="failed", reason_code="PLANNER_FAILED", payload={"depth": depth})
            return await finish(_terminal("FAILED", "PLANNER_FAILED", depth, limits, started, deadline))
        await audit.record(AgentEventType.PLANNER_DECISION, outcome="selected" if step else "complete", payload={"depth": depth})
        if step is None:
            return await finish(_terminal("COMPLETE", None, depth, limits, started, deadline, observation))
        await audit.record(AgentEventType.TOOL_SELECTED, payload={
            "depth": depth,
            "tool": _audit_identifier(step.tool, "tool"),
            "capability": _audit_identifier(step.capability, "capability"),
        })
        try:
            decision = await _invoke_within_deadline(
                authorize, step, deadline=deadline, clock=clock,
            )
        except TimeoutError:
            await audit.record(AgentEventType.AUTHORIZATION_DECISION, outcome="timeout", reason_code="RUN_DEADLINE_EXCEEDED", payload={"depth": depth})
            return await finish(_terminal("TIMEOUT", "RUN_DEADLINE_EXCEEDED", depth, limits, started, deadline))
        except Exception:
            await audit.record(AgentEventType.AUTHORIZATION_DECISION, outcome="failed", reason_code="AUTHORIZATION_FAILED", payload={"depth": depth})
            return await finish(_terminal("FAILED", "AUTHORIZATION_FAILED", depth, limits, started, deadline))
        decision_reason = _reason_code(getattr(decision, "reason_code", "UNAUTHORIZED"))
        await audit.record(
            AgentEventType.AUTHORIZATION_DECISION,
            outcome="allowed" if getattr(decision, "allowed", False) else "denied",
            reason_code=decision_reason,
            payload={"depth": depth},
        )
        if not getattr(decision, "allowed", False):
            return await finish(_terminal(
                "DENIED", decision_reason,
                depth, limits, started, deadline, observation,
            ))
        budget_decision = budget.consume()
        budget_reason = _reason_code(budget_decision.reason_code)
        await audit.record(
            AgentEventType.BUDGET_DECISION,
            outcome="allowed" if budget_decision.allowed else "denied",
            reason_code=budget_reason,
            payload={"depth": depth, "remaining_executions": budget_decision.remaining_executions},
        )
        if not budget_decision.allowed:
            reason = budget_reason
            status = "TIMEOUT" if reason == "TIME_BUDGET_EXHAUSTED" else "BUDGET_EXHAUSTED"
            return await finish(_terminal(status, reason, depth, limits, started, deadline, observation))
        remaining = deadline - clock()
        if remaining <= 0:
            return await finish(_terminal("TIMEOUT", "RUN_DEADLINE_EXCEEDED", depth, limits, started, deadline))
        await audit.record(AgentEventType.TOOL_EXECUTION_STARTED, payload={
            "depth": depth, "tool": _audit_identifier(step.tool, "tool"),
        })
        try:
            observation = await asyncio.wait_for(
                execute(step), timeout=min(limits.tool_timeout_seconds, remaining),
            )
        except TimeoutError:
            reason = "RUN_DEADLINE_EXCEEDED" if clock() >= deadline else "TOOL_TIMEOUT"
            await audit.record(AgentEventType.TOOL_EXECUTION_FAILED, outcome="timeout", reason_code=reason, payload={"depth": depth, "tool": _audit_identifier(step.tool, "tool")})
            return await finish(_terminal("TIMEOUT", reason, depth, limits, started, deadline, observation))
        except asyncio.CancelledError:
            await audit.record(AgentEventType.TOOL_EXECUTION_FAILED, outcome="cancelled", reason_code="RUN_CANCELLED", payload={"depth": depth, "tool": _audit_identifier(step.tool, "tool")})
            await finish(_terminal("CANCELLED", "RUN_CANCELLED", depth, limits, started, deadline, observation))
            raise
        except Exception:
            await audit.record(AgentEventType.TOOL_EXECUTION_FAILED, outcome="failed", reason_code="TOOL_FAILED", payload={"depth": depth, "tool": _audit_identifier(step.tool, "tool")})
            return await finish(_terminal("FAILED", "TOOL_FAILED", depth, limits, started, deadline, observation))
        await audit.record(AgentEventType.TOOL_EXECUTION_COMPLETED, outcome="completed", payload={"depth": depth, "tool": _audit_identifier(step.tool, "tool")})
        depth += 1
        await audit.record(AgentEventType.OBSERVATION_RECEIVED, payload={
            "depth": depth,
            "observation_type": type(observation).__name__,
            "observation_sha256": _audit_fingerprint(observation),
        })
    return await finish(_terminal("DEPTH_LIMIT_REACHED", "MAX_DEPTH_REACHED", depth, limits, started, deadline, observation))


async def _invoke_within_deadline(function, *args, deadline, clock):
    remaining = deadline - clock()
    if remaining <= 0:
        raise TimeoutError
    value = function(*args) if inspect.iscoroutinefunction(function) else asyncio.to_thread(function, *args)
    result = await asyncio.wait_for(value, timeout=remaining)
    if inspect.isawaitable(result):
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError
        return await asyncio.wait_for(result, timeout=remaining)
    return result


def _terminal(status, reason, depth, limits, started, deadline, observation=None):
    return LoopOutcome(
        status=status,
        observation=observation,
        reason_code=reason,
        steps=depth,
        termination_context=MappingProxyType({
            "completed_depth": depth,
            "max_depth": limits.max_depth,
            "timeout_seconds": limits.timeout_seconds,
            "deadline_offset_seconds": deadline - started,
        }),
    )


def _finite_positive(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _is_async_callable(value) -> bool:
    return inspect.iscoroutinefunction(value) or inspect.iscoroutinefunction(getattr(value, "__call__", None))


def _audit_fingerprint(value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _audit_identifier(value, kind: str) -> str:
    rendered = str(value)
    if rendered and len(rendered) <= 128 and all(char.isalnum() or char in "_.:-" for char in rendered):
        return rendered
    return f"{kind}:sha256:{hashlib.sha256(rendered.encode('utf-8')).hexdigest()[:16]}"


def _reason_code(value) -> str:
    rendered = str(value)
    if rendered and len(rendered) <= 64 and all(char.isupper() or char.isdigit() or char == "_" for char in rendered):
        return rendered
    return "UNSAFE_REASON_CODE"