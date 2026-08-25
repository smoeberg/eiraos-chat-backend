"""F6-03 authorization boundary for tool capability execution."""

from dataclasses import dataclass
from typing import FrozenSet

from .tool_registry import Tool


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    """Inputs to an authorization decision."""

    actor: str
    tool: Tool
    capability: str
    allowed_capabilities: FrozenSet[str] = frozenset()


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    """Explicit, audit-safe authorization result."""

    allowed: bool
    reason_code: str


def authorize(request: AuthorizationRequest) -> AuthorizationDecision:
    """Return a deterministic allow/deny decision; default is deny."""
    if not request.actor or not request.capability:
        return AuthorizationDecision(False, "INVALID_REQUEST")
    if request.capability not in request.tool.capabilities:
        return AuthorizationDecision(False, "CAPABILITY_NOT_DECLARED")
    if request.capability not in request.allowed_capabilities:
        return AuthorizationDecision(False, "CAPABILITY_NOT_AUTHORIZED")
    return AuthorizationDecision(True, "AUTHORIZED")
