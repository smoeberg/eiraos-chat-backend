"""F3-01 capability contract.

This module models authority; it does not perform HTTP authorization.  F3-02
will bind every operation to this contract at the application boundary.
Unknown roles, scopes and capabilities are deliberately denied.
"""

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import AbstractSet, Iterable, Mapping


class Capability(StrEnum):
    ORGANIZATION_READ = "organization:read"
    ORGANIZATION_UPDATE = "organization:update"
    MEMBER_INVITE = "member:invite"
    MEMBER_REMOVE = "member:remove"
    MEMBER_MANAGE = "member:manage"
    BOT_READ = "bot:read"
    BOT_CREATE = "bot:create"
    BOT_UPDATE = "bot:update"
    BOT_DELETE = "bot:delete"
    DOCUMENT_READ = "document:read"
    DOCUMENT_UPLOAD = "document:upload"
    DOCUMENT_DELETE = "document:delete"
    CONVERSATION_READ = "conversation:read"
    CONVERSATION_CREATE = "conversation:create"
    CONVERSATION_DELETE = "conversation:delete"
    MEMORY_READ = "memory:read"
    MEMORY_WRITE = "memory:write"
    MEMORY_DELETE = "memory:delete"
    USAGE_READ = "usage:read"
    SECRET_MANAGE = "secret:manage"
    PROVIDER_EXECUTE = "provider:execute"
    TOOL_EXECUTE_STANDARD = "tool:execute:standard"
    TOOL_EXECUTE_ELEVATED = "tool:execute:elevated"


class PrincipalType(StrEnum):
    USER = "user"
    ORGANIZATION = "organization"
    BOT = "bot"
    EXECUTION = "execution"


@dataclass(frozen=True, slots=True)
class Principal:
    kind: PrincipalType
    identifier: str
    organization_id: int

    def __post_init__(self) -> None:
        if not self.identifier or self.organization_id <= 0:
            raise ValueError("principal identity and organization must be explicit")


@dataclass(frozen=True, slots=True)
class CapabilitySet:
    """An immutable, tenant-bound grant."""

    principal: Principal
    capabilities: frozenset[Capability]

    @classmethod
    def create(cls, principal: Principal, capabilities: Iterable[Capability]) -> "CapabilitySet":
        return cls(principal=principal, capabilities=frozenset(capabilities))

    def allows(self, capability: Capability, *, organization_id: int) -> bool:
        return organization_id == self.principal.organization_id and capability in self.capabilities


@dataclass(frozen=True, slots=True)
class CapabilityDecision:
    allowed: bool
    capability: Capability | str
    reason: str


_OWNER = frozenset(Capability)
_ADMIN = _OWNER - {Capability.ORGANIZATION_UPDATE, Capability.MEMBER_MANAGE, Capability.SECRET_MANAGE}
_MEMBER = frozenset({
    Capability.BOT_READ,
    Capability.DOCUMENT_READ,
    Capability.DOCUMENT_UPLOAD,
    Capability.CONVERSATION_READ,
    Capability.CONVERSATION_CREATE,
    Capability.CONVERSATION_DELETE,
    Capability.MEMORY_READ,
    Capability.MEMORY_WRITE,
    Capability.MEMORY_DELETE,
    Capability.USAGE_READ,
    Capability.PROVIDER_EXECUTE,
    Capability.TOOL_EXECUTE_STANDARD,
})
_VIEWER = frozenset({
    Capability.BOT_READ,
    Capability.DOCUMENT_READ,
    Capability.CONVERSATION_READ,
    Capability.MEMORY_READ,
})

ROLE_CAPABILITIES: Mapping[str, frozenset[Capability]] = MappingProxyType({
    "owner": _OWNER,
    "admin": _ADMIN,
    "member": _MEMBER,
    "viewer": _VIEWER,
})

BOT_SCOPE_CAPABILITIES: Mapping[str, frozenset[Capability]] = MappingProxyType({
    "restricted": frozenset({Capability.PROVIDER_EXECUTE}),
    "standard": frozenset({Capability.PROVIDER_EXECUTE, Capability.TOOL_EXECUTE_STANDARD}),
    "elevated": frozenset({
        Capability.PROVIDER_EXECUTE,
        Capability.TOOL_EXECUTE_STANDARD,
        Capability.TOOL_EXECUTE_ELEVATED,
    }),
})


def _coerce_capability(value: Capability | str) -> Capability | None:
    try:
        return value if isinstance(value, Capability) else Capability(value)
    except (TypeError, ValueError):
        return None


def decide_role_capability(
    *, role: str, capability: Capability | str, principal_organization_id: int, resource_organization_id: int
) -> CapabilityDecision:
    """Evaluate the static role grant without consulting transport state."""

    parsed = _coerce_capability(capability)
    if parsed is None:
        return CapabilityDecision(False, str(capability), "unknown_capability")
    if principal_organization_id != resource_organization_id:
        return CapabilityDecision(False, parsed, "tenant_mismatch")
    grants = ROLE_CAPABILITIES.get((role or "").strip().lower())
    if grants is None:
        return CapabilityDecision(False, parsed, "unknown_role")
    if parsed not in grants:
        return CapabilityDecision(False, parsed, "capability_not_granted")
    return CapabilityDecision(True, parsed, "granted")


def derive_execution_capabilities(
    *, user_grant: CapabilitySet, bot_principal: Principal, bot_scope: str,
    requested: AbstractSet[Capability], execution_id: str,
) -> CapabilitySet:
    """Derive least privilege for one execution from user and bot grants.

    The execution receives only explicitly requested capabilities present in
    both grants. Cross-tenant principals and unknown bot scopes fail closed.
    """

    if user_grant.principal.kind is not PrincipalType.USER:
        raise ValueError("execution authority must originate from a user grant")
    if bot_principal.kind is not PrincipalType.BOT:
        raise ValueError("bot principal required")
    if user_grant.principal.organization_id != bot_principal.organization_id:
        raise PermissionError("cross-tenant execution grant denied")
    bot_grants = BOT_SCOPE_CAPABILITIES.get((bot_scope or "").strip().lower(), frozenset())
    effective = frozenset(requested) & user_grant.capabilities & bot_grants
    execution = Principal(PrincipalType.EXECUTION, execution_id, bot_principal.organization_id)
    return CapabilitySet(execution, effective)