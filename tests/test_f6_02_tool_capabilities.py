import pytest

from eiraos.application.tool_registry import Tool, ToolRegistry


def make_tool(capabilities: tuple[str, ...] | list[str]) -> Tool:
    return Tool(
        name="calendar.tool",
        version="1.0",
        description="Calendar tool",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        capabilities=capabilities,
    )


def test_capabilities_are_normalized_and_deduplicated() -> None:
    tool = make_tool(["calendar.write", "calendar.read", "calendar.write"])

    assert tool.capabilities == ("calendar.read", "calendar.write")


def test_capabilities_are_immutable() -> None:
    tool = make_tool(["calendar.read"])

    with pytest.raises(AttributeError):
        tool.capabilities = ("calendar.write",)


def test_capabilities_are_discoverable_through_registry() -> None:
    registry = ToolRegistry()
    tool = make_tool(["calendar.read"])
    registry.register(tool)

    assert registry.get("calendar.tool").capabilities == ("calendar.read",)


def test_read_and_write_capabilities_are_independent() -> None:
    read_tool = make_tool(["calendar.read"])
    write_tool = Tool(
        name="calendar.write.tool",
        version="1.0",
        description="Calendar writer",
        input_schema={},
        output_schema={},
        capabilities=["calendar.write"],
    )

    assert read_tool.capabilities == ("calendar.read",)
    assert write_tool.capabilities == ("calendar.write",)


@pytest.mark.parametrize(
    "capabilities",
    [
        [""],
        ["calendar..read"],
        [" calendar.read"],
        ["calendar.read "],
        ["calendar. read"],
        ["calendar read"],
        [1],
    ],
)
def test_invalid_capability_identifiers_are_rejected(capabilities: list[object]) -> None:
    with pytest.raises(ValueError):
        make_tool(capabilities)  # type: ignore[arg-type]


def test_tool_without_capabilities_remains_valid() -> None:
    tool = make_tool([])

    assert tool.capabilities == ()


def test_capability_metadata_does_not_authorize_execution() -> None:
    tool = make_tool(["calendar.write"])

    assert not hasattr(tool, "authorize")
    assert not hasattr(tool, "execute")
