"""F6-01 tool metadata and registry contract implementation."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


class ToolRegistryError(Exception):
    """Base exception for tool registry failures."""


class DuplicateToolError(ToolRegistryError):
    """Raised when a tool name is already registered."""


class ToolNotFoundError(ToolRegistryError):
    """Raised when a requested tool is not registered."""


@dataclass(frozen=True, slots=True)
class Tool:
    """Immutable descriptive metadata for a registered tool.

    The registry intentionally contains no execution behaviour, authorization,
    capability, budget, timeout, or audit logic.
    """

    name: str
    version: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("tool name must not be empty")
        if not self.version.strip():
            raise ValueError("tool version must not be empty")
        if not self.description.strip():
            raise ValueError("tool description must not be empty")
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "version", self.version.strip())
        object.__setattr__(self, "description", self.description.strip())
        object.__setattr__(self, "input_schema", MappingProxyType(dict(self.input_schema)))
        object.__setattr__(self, "output_schema", MappingProxyType(dict(self.output_schema)))


class ToolRegistry:
    """Process-local registry for discovering tool metadata."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise DuplicateToolError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"tool not found: {name}") from exc

    def list(self) -> tuple[Tool, ...]:
        return tuple(self._tools[name] for name in sorted(self._tools))
