import pytest

from eiraos.application.tool_registry import (
    DuplicateToolError,
    Tool,
    ToolNotFoundError,
    ToolRegistry,
)


def make_tool(name: str = "knowledge.search") -> Tool:
    return Tool(
        name=name,
        version="1.0",
        description="Search tenant knowledge",
        input_schema={"type": "object"},
        output_schema={"type": "array"},
    )


def test_register_and_get_returns_registered_tool() -> None:
    registry = ToolRegistry()
    tool = make_tool()

    registry.register(tool)

    assert registry.get(tool.name) is tool


def test_duplicate_registration_is_rejected() -> None:
    registry = ToolRegistry()
    registry.register(make_tool())

    with pytest.raises(DuplicateToolError, match="knowledge.search"):
        registry.register(make_tool())


def test_unknown_tool_has_defined_error() -> None:
    registry = ToolRegistry()

    with pytest.raises(ToolNotFoundError, match="missing.tool"):
        registry.get("missing.tool")


def test_list_is_deterministic_by_tool_name() -> None:
    registry = ToolRegistry()
    registry.register(make_tool("z.tool"))
    registry.register(make_tool("a.tool"))

    assert [tool.name for tool in registry.list()] == ["a.tool", "z.tool"]


def test_tool_metadata_is_immutable_after_registration() -> None:
    tool = make_tool()
    registry = ToolRegistry()
    registry.register(tool)

    with pytest.raises((AttributeError, TypeError)):
        tool.description = "changed"

    with pytest.raises(TypeError):
        tool.input_schema["type"] = "changed"


def test_registry_does_not_execute_tools() -> None:
    class NonExecutableTool(Tool):
        pass

    registry = ToolRegistry()
    tool = NonExecutableTool(
        name="read.only",
        version="1.0",
        description="Metadata only",
        input_schema={},
        output_schema={},
    )

    registry.register(tool)

    assert registry.get("read.only") is tool
