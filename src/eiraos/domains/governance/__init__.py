"""Governance domain contracts."""

from .capabilities import (
    BOT_SCOPE_CAPABILITIES,
    ROLE_CAPABILITIES,
    Capability,
    CapabilityDecision,
    CapabilitySet,
    Principal,
    PrincipalType,
    decide_role_capability,
    derive_execution_capabilities,
)

__all__ = [
    "BOT_SCOPE_CAPABILITIES",
    "ROLE_CAPABILITIES",
    "Capability",
    "CapabilityDecision",
    "CapabilitySet",
    "Principal",
    "PrincipalType",
    "decide_role_capability",
    "derive_execution_capabilities",
]
