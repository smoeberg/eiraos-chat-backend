import pytest

from eiraos.application.agent_loop import AgentRunLimits, LoopStep
from eiraos.application.agent_runtime import AgentAuthority, GovernedAgentRuntime, ToolBindingError
from eiraos.application.execution_budget import ExecutionBudget
from eiraos.application.tool_registry import Tool, ToolRegistry


class Audit:
    def __init__(self):
        self.events = []

    async def record(self, event_type, **fields):
        self.events.append((event_type.value, fields))


def runtime(calls):
    registry = ToolRegistry()
    registry.register(Tool(
        "knowledge.search", "1", "Search tenant knowledge",
        {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}, "additionalProperties": False},
        {"type": "object", "required": ["count"], "properties": {"count": {"type": "integer"}}},
        ("knowledge.read",),
    ))

    async def execute(arguments, context):
        calls.append((dict(arguments), context))
        return {"count": 1}

    return GovernedAgentRuntime(registry, {"knowledge.search": execute})


def authority(**overrides):
    values = dict(actor="user:1", organization_id=1, resource_organization_id=1, allowed_capabilities=frozenset({"knowledge.read"}))
    values.update(overrides)
    return AgentAuthority(**values)


@pytest.mark.asyncio
async def test_gate_executes_only_through_authorized_tenant_bound_dispatch():
    calls = []
    audit = Audit()

    def planner(conversation, observation):
        return None if observation else LoopStep("knowledge.search", "knowledge.read", {"query": "hello"})

    outcome = await runtime(calls).run(
        planner=planner, conversation="conversation", authority=authority(),
        budget=ExecutionBudget(2, 10), limits=AgentRunLimits(2, 2, 1), audit=audit,
    )
    assert outcome.status == "COMPLETE" and len(calls) == 1
    assert calls[0][1].organization_id == 1
    event_types = [event for event, _ in audit.events]
    assert event_types.index("authorization.decision") < event_types.index("tool.execution.started")
    assert event_types.index("budget.decision") < event_types.index("tool.execution.started")


@pytest.mark.asyncio
@pytest.mark.parametrize("requested_authority,tool,capability,reason", [
    (authority(resource_organization_id=2), "knowledge.search", "knowledge.read", "TENANT_MISMATCH"),
    (authority(), "missing.tool", "knowledge.read", "UNKNOWN_TOOL"),
    (authority(allowed_capabilities=frozenset()), "knowledge.search", "knowledge.read", "CAPABILITY_NOT_AUTHORIZED"),
    (authority(), "knowledge.search", "knowledge.write", "CAPABILITY_NOT_DECLARED"),
])
async def test_negative_authorization_paths_never_dispatch(requested_authority, tool, capability, reason):
    calls = []
    outcome = await runtime(calls).run(
        planner=lambda conversation, observation: LoopStep(tool, capability, {"query": "hello"}),
        conversation="conversation", authority=requested_authority,
        budget=ExecutionBudget(1, 10), limits=AgentRunLimits(1, 1, 1), audit=Audit(),
    )
    assert outcome.status == "DENIED" and outcome.reason_code == reason
    assert calls == []


@pytest.mark.asyncio
async def test_invalid_arguments_fail_before_executor_side_effect():
    calls = []
    outcome = await runtime(calls).run(
        planner=lambda conversation, observation: LoopStep("knowledge.search", "knowledge.read", {"unexpected": "x"}),
        conversation="conversation", authority=authority(), budget=ExecutionBudget(1, 10),
        limits=AgentRunLimits(1, 1, 1), audit=Audit(),
    )
    assert outcome.status == "FAILED" and outcome.reason_code == "TOOL_FAILED"
    assert calls == []


def test_runtime_requires_one_cancellable_executor_per_registered_tool():
    registry = ToolRegistry()
    registry.register(Tool("safe", "1", "safe", {}, {}, ("read",)))
    with pytest.raises(ToolBindingError):
        GovernedAgentRuntime(registry, {})
    with pytest.raises(ToolBindingError):
        GovernedAgentRuntime(registry, {"safe": lambda arguments, context: None})

    async def execute(arguments, context):
        return None

    with pytest.raises(ToolBindingError, match="no registered tool"):
        GovernedAgentRuntime(registry, {"safe": execute, "unknown": execute})


def test_tool_schema_is_deeply_immutable_and_name_is_machine_safe():
    tool = Tool("safe.tool", "1", "safe", {"properties": {"q": {"type": "string"}}}, {}, ())
    with pytest.raises(TypeError):
        tool.input_schema["properties"]["q"]["type"] = "integer"
    with pytest.raises(ValueError):
        Tool("unsafe tool", "1", "unsafe", {}, {}, ())
    with pytest.raises(ValueError, match="keys"):
        LoopStep("safe.tool", "read", {1: "collision"})


def test_step_authority_and_runtime_registry_snapshot_are_immutable():
    arguments = {"query": ["original"]}
    step = LoopStep("knowledge.search", "knowledge.read", arguments)
    arguments["query"].append("tampered")
    assert step.arguments["query"] == ("original",)
    with pytest.raises(TypeError):
        step.arguments["query"] = ("changed",)

    grants = {"knowledge.read"}
    bound_authority = authority(allowed_capabilities=grants)
    grants.clear()
    assert bound_authority.allowed_capabilities == frozenset({"knowledge.read"})

    registry = ToolRegistry()
    registry.register(Tool("first", "1", "first", {}, {}, ("read",)))

    async def execute(arguments, context):
        return None

    bound_runtime = GovernedAgentRuntime(registry, {"first": execute})
    registry.register(Tool("late", "1", "late", {}, {}, ("read",)))
    assert "late" not in bound_runtime._tools