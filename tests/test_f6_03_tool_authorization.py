from eiraos.application.tool_authorization import AuthorizationRequest, authorize
from eiraos.application.tool_registry import Tool


def make_tool(capabilities=("read",)):
    return Tool("example", "1.0", "Example", {}, {}, capabilities)


def test_authorized_capability_is_allowed():
    result = authorize(AuthorizationRequest("actor-1", make_tool(), "read", frozenset({"read"})))
    assert result.allowed is True
    assert result.reason_code == "AUTHORIZED"


def test_undeclared_capability_is_denied():
    result = authorize(AuthorizationRequest("actor-1", make_tool(), "write", frozenset({"write"})))
    assert result.allowed is False
    assert result.reason_code == "CAPABILITY_NOT_DECLARED"


def test_declared_but_unauthorized_capability_is_denied():
    result = authorize(AuthorizationRequest("actor-1", make_tool(), "read"))
    assert result.allowed is False
    assert result.reason_code == "CAPABILITY_NOT_AUTHORIZED"


def test_missing_actor_is_denied():
    result = authorize(AuthorizationRequest("", make_tool(), "read", frozenset({"read"})))
    assert result.allowed is False
    assert result.reason_code == "INVALID_REQUEST"
