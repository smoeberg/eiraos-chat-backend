import asyncio
import math

import pytest

from eiraos.application.agent_loop import AgentRunLimits, LoopStep, run_agent_loop_async
from eiraos.application.execution_budget import ExecutionBudget
from eiraos.application.tool_authorization import AuthorizationDecision


STEP = LoopStep("example", "read", {})
ALLOW = lambda step: AuthorizationDecision(True, "AUTHORIZED")


@pytest.mark.asyncio
async def test_depth_is_enforced_before_an_additional_execution():
    calls = []

    async def execute(step):
        calls.append(step.tool)
        return "again"

    outcome = await run_agent_loop_async(
        lambda conversation, observation: STEP,
        ALLOW,
        ExecutionBudget(10, 10),
        execute,
        "conversation",
        limits=AgentRunLimits(2, 2, 1),
    )
    assert outcome.status == "DEPTH_LIMIT_REACHED"
    assert outcome.reason_code == "MAX_DEPTH_REACHED"
    assert outcome.steps == 2 and calls == ["example", "example"]
    assert outcome.termination_context["completed_depth"] == 2


@pytest.mark.asyncio
async def test_running_tool_is_cancelled_at_tool_timeout():
    cancelled = asyncio.Event()

    async def execute(step):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()

    outcome = await run_agent_loop_async(
        lambda conversation, observation: STEP,
        ALLOW,
        ExecutionBudget(2, 10),
        execute,
        "conversation",
        limits=AgentRunLimits(2, 1, 0.01),
    )
    assert outcome.status == "TIMEOUT" and outcome.reason_code == "TOOL_TIMEOUT"
    assert outcome.steps == 0 and cancelled.is_set()


@pytest.mark.asyncio
async def test_deadline_covers_async_planning_before_tool_execution():
    calls = []

    async def planner(conversation, observation):
        await asyncio.sleep(10)
        return STEP

    async def execute(step):
        calls.append(step)

    outcome = await run_agent_loop_async(
        planner, ALLOW, ExecutionBudget(1, 10), execute, "conversation",
        limits=AgentRunLimits(1, 0.01, 0.005),
    )
    assert outcome.status == "TIMEOUT"
    assert outcome.reason_code == "RUN_DEADLINE_EXCEEDED"
    assert calls == []


@pytest.mark.asyncio
async def test_non_cancellable_executor_fails_before_planning():
    planned = []
    outcome = await run_agent_loop_async(
        lambda conversation, observation: planned.append(True) or STEP,
        ALLOW,
        ExecutionBudget(1, 10),
        lambda step: "unsafe",
        "conversation",
        limits=AgentRunLimits(1, 1, 1),
    )
    assert outcome.status == "DENIED"
    assert outcome.reason_code == "NON_CANCELLABLE_EXECUTOR"
    assert planned == []


@pytest.mark.asyncio
async def test_async_callable_tool_adapter_is_supported():
    class Adapter:
        async def __call__(self, step):
            return "done"

    outcome = await run_agent_loop_async(
        lambda conversation, observation: None if observation else STEP,
        ALLOW, ExecutionBudget(1, 10), Adapter(), "conversation",
        limits=AgentRunLimits(1, 1, 1),
    )
    assert outcome.status == "DEPTH_LIMIT_REACHED"
    assert outcome.observation == "done"


@pytest.mark.parametrize("depth,run_timeout,tool_timeout", [
    (0, 1, 1),
    (True, 1, 1),
    (1, 0, 1),
    (1, math.inf, 1),
    (1, 1, math.nan),
    (1, 1, 2),
])
def test_invalid_limits_fail_closed(depth, run_timeout, tool_timeout):
    with pytest.raises(ValueError):
        AgentRunLimits(depth, run_timeout, tool_timeout)