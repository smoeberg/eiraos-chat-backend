from eiraos.application.agent_loop import LoopStep, run_agent_loop
from eiraos.application.execution_budget import ExecutionBudget
from eiraos.application.tool_authorization import AuthorizationDecision


def test_loop_executes_and_observes():
    calls = []

    def planner(conversation, observation):
        return None if observation else LoopStep("example", "read", {})

    def execute(step):
        calls.append(step.tool)
        return {"ok": True}

    outcome = run_agent_loop(
        planner,
        lambda step: AuthorizationDecision(True, "AUTHORIZED"),
        ExecutionBudget(2, 10),
        execute,
        "hello",
        max_steps=2,
    )
    assert outcome.status == "COMPLETE"
    assert calls == ["example"]
    assert outcome.observation == {"ok": True}


def test_unauthorized_step_does_not_execute():
    calls = []
    step = LoopStep("example", "read", {})
    outcome = run_agent_loop(
        lambda conversation, observation: step,
        lambda requested: AuthorizationDecision(False, "CAPABILITY_NOT_AUTHORIZED"),
        ExecutionBudget(1, 10),
        lambda requested: calls.append(requested),
        "hello",
    )
    assert outcome.status == "DENIED"
    assert outcome.reason_code == "CAPABILITY_NOT_AUTHORIZED"
    assert calls == []


def test_budget_exhaustion_prevents_execution():
    step = LoopStep("example", "read", {})
    calls = []
    outcome = run_agent_loop(
        lambda conversation, observation: step,
        lambda requested: AuthorizationDecision(True, "AUTHORIZED"),
        ExecutionBudget(0, 10),
        lambda requested: calls.append(requested),
        "hello",
    )
    assert outcome.status == "BUDGET_EXHAUSTED"
    assert calls == []


def test_step_limit_is_terminal():
    step = LoopStep("example", "read", {})
    outcome = run_agent_loop(
        lambda conversation, observation: step,
        lambda requested: AuthorizationDecision(True, "AUTHORIZED"),
        ExecutionBudget(3, 10),
        lambda requested: {"next": True},
        "hello",
        max_steps=2,
    )
    assert outcome.status == "STEP_LIMIT_REACHED"
    assert outcome.reason_code == "MAX_STEPS_REACHED"
    assert outcome.steps == 2
