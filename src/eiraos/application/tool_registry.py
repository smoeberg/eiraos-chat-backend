"""F6 tool metadata, capability declarations, and registry discovery."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


class ToolRegistryError(Exception):
    """Base exception for tool registry failures."""


class DuplicateToolError(ToolRegistryError):
    """Raised when a tool name is already registered."""


class ToolNotFoundError(ToolRegistryError):
    """Raised when a requested tool is not registered."""


def _normalize_capabilities(capabilities: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Validate and deterministically normalize a tool's capabilities."""
    normalized: set[str] = set()
    for capability in capabilities:
        if not isinstance(capability, str):
            raise ValueError("capability must be a string")
        if not capability or capability != capability.strip():
            raise ValueError("capability must not contain whitespace")
        segments = capability.split(".")
        if any(not segment for segment in segments):
            raise ValueError("capability must contain non-empty dot-separated segments")
        if any(any(char.isspace() for char in segment) for segment in segments):
            raise ValueError("capability must not contain whitespace")
        normalized.add(capability)
    return tuple(sorted(normalized))


def _freeze(value):
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("schema keys must be strings")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class Tool:
    """Immutable descriptive metadata for a registered tool."""

    name: str
    version: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("tool name must not be empty")
        if not self.version.strip():
            raise ValueError("tool version must not be empty")
        if not self.description.strip():
            raise ValueError("tool description must not be empty")
        if any(not (char.isalnum() or char in "_.-") for char in self.name.strip()):
            raise ValueError("tool name must be a stable machine identifier")
        if not isinstance(self.capabilities, (tuple, list)):
            raise ValueError("capabilities must be a sequence of strings")
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "version", self.version.strip())
        object.__setattr__(self, "description", self.description.strip())
        object.__setattr__(self, "input_schema", _freeze(self.input_schema))
        object.__setattr__(self, "output_schema", _freeze(self.output_schema))
        object.__setattr__(self, "capabilities", _normalize_capabilities(self.capabilities))


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