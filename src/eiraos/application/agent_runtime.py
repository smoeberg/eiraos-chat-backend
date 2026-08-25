"""F6 gate: composed governed tool execution boundary."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Awaitable, Callable, FrozenSet, Mapping

from eiraos.application.agent_loop import AgentRunLimits, LoopStep, run_agent_loop_async
from eiraos.application.tool_authorization import AuthorizationDecision, AuthorizationRequest, authorize
from eiraos.application.tool_registry import Tool, ToolRegistry
from eiraos.application.tool_registry import ToolNotFoundError


class ToolBindingError(ValueError):
    pass


class ToolSchemaError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AgentAuthority:
    actor: str
    organization_id: int
    resource_organization_id: int
    allowed_capabilities: FrozenSet[str]

    def __post_init__(self):
        if not self.actor or self.organization_id <= 0 or self.resource_organization_id <= 0:
            raise ValueError("agent authority identity and tenant must be explicit")
        if not all(isinstance(item, str) and item for item in self.allowed_capabilities):
            raise ValueError("allowed capabilities must be explicit strings")
        object.__setattr__(self, "allowed_capabilities", frozenset(self.allowed_capabilities))


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    actor: str
    organization_id: int
    capability: str


class GovernedAgentRuntime:
    def __init__(
        self,
        registry: ToolRegistry,
        executors: Mapping[str, Callable[[Mapping, ToolExecutionContext], Awaitable[object]]],
    ):
        bound = dict(executors)
        for name, executor in bound.items():
            try:
                tool = registry.get(name)
            except ToolNotFoundError as exc:
                raise ToolBindingError(f"executor has no registered tool: {name}") from exc
            if not callable(executor) or not _is_async_callable(executor):
                raise ToolBindingError(f"tool executor must be async: {name}")
            if tool.name != name:
                raise ToolBindingError("tool binding identity mismatch")
        tools = {tool.name: tool for tool in registry.list()}
        registered = set(tools)
        if registered != set(bound):
            raise ToolBindingError("every registered tool requires exactly one executor")
        self._tools = MappingProxyType(tools)
        self._executors = MappingProxyType(bound)

    async def run(self, *, planner, conversation, authority: AgentAuthority, budget, limits: AgentRunLimits, audit):
        permits: dict[int, tuple[Tool, str]] = {}

        def policy(step: LoopStep) -> AuthorizationDecision:
            if authority.organization_id != authority.resource_organization_id:
                return AuthorizationDecision(False, "TENANT_MISMATCH")
            try:
                tool = self._tools[step.tool]
            except KeyError:
                return AuthorizationDecision(False, "UNKNOWN_TOOL")
            decision = authorize(AuthorizationRequest(
                actor=authority.actor,
                tool=tool,
                capability=step.capability,
                allowed_capabilities=authority.allowed_capabilities,
            ))
            if decision.allowed:
                permits[id(step)] = (tool, step.capability)
            return decision

        async def dispatch(step: LoopStep):
            permit = permits.pop(id(step), None)
            if permit is None:
                raise PermissionError("tool dispatch has no authorization permit")
            tool, capability = permit
            _validate_schema(step.arguments, tool.input_schema, path="arguments")
            context = ToolExecutionContext(
                actor=authority.actor,
                organization_id=authority.organization_id,
                capability=capability,
            )
            result = await self._executors[tool.name](MappingProxyType(dict(step.arguments)), context)
            _validate_schema(result, tool.output_schema, path="result")
            return result

        return await run_agent_loop_async(
            planner, policy, budget, dispatch, conversation,
            limits=limits, audit=audit,
        )


def _is_async_callable(value) -> bool:
    import inspect
    return inspect.iscoroutinefunction(value) or inspect.iscoroutinefunction(getattr(value, "__call__", None))


def _validate_schema(value, schema, *, path):
    if not schema:
        return
    expected = schema.get("type")
    checks = {
        "object": lambda item: isinstance(item, Mapping),
        "array": lambda item: isinstance(item, (list, tuple)),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if expected in checks and not checks[expected](value):
        raise ToolSchemaError(f"{path} does not match declared type")
    if expected == "object":
        required = tuple(schema.get("required", ()))
        for key in required:
            if key not in value:
                raise ToolSchemaError(f"{path} is missing required property")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and any(key not in properties for key in value):
            raise ToolSchemaError(f"{path} contains an undeclared property")
        for key, child_schema in properties.items():
            if key in value:
                _validate_schema(value[key], child_schema, path=f"{path}.{key}")
    if expected == "array" and "items" in schema:
        for index, item in enumerate(value):
            _validate_schema(item, schema["items"], path=f"{path}[{index}]")