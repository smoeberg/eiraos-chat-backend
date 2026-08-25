import pytest

from eiraos.domains.governance.capabilities import (
    ROLE_CAPABILITIES,
    Capability,
    CapabilitySet,
    Principal,
    PrincipalType,
    decide_role_capability,
    derive_execution_capabilities,
)


def _principal(kind: PrincipalType, identifier: str, organization_id: int = 7) -> Principal:
    return Principal(kind, identifier, organization_id)


def test_all_persisted_roles_have_explicit_immutable_grants():
    assert set(ROLE_CAPABILITIES) == {"owner", "admin", "member", "viewer"}
    assert all(isinstance(grants, frozenset) for grants in ROLE_CAPABILITIES.values())


@pytest.mark.parametrize("role", ["", "superadmin", "OWNER "])
def test_unknown_role_denied_and_known_role_normalized(role):
    decision = decide_role_capability(
        role=role,
        capability=Capability.CONVERSATION_READ,
        principal_organization_id=7,
        resource_organization_id=7,
    )
    assert decision.allowed is (role == "OWNER ")
    assert decision.reason == ("granted" if role == "OWNER " else "unknown_role")


def test_unknown_capability_fails_closed():
    decision = decide_role_capability(
        role="owner", capability="platform:root", principal_organization_id=7, resource_organization_id=7
    )
    assert decision.allowed is False
    assert decision.capability == "platform:root"
    assert decision.reason == "unknown_capability"


def test_role_grant_never_crosses_tenant_boundary():
    decision = decide_role_capability(
        role="owner", capability=Capability.ORGANIZATION_UPDATE,
        principal_organization_id=7, resource_organization_id=8,
    )
    assert decision.allowed is False
    assert decision.reason == "tenant_mismatch"


def test_capability_set_is_tenant_bound():
    grant = CapabilitySet.create(_principal(PrincipalType.USER, "42"), {Capability.CONVERSATION_CREATE})
    assert grant.allows(Capability.CONVERSATION_CREATE, organization_id=7)
    assert not grant.allows(Capability.CONVERSATION_CREATE, organization_id=8)


def test_execution_receives_intersection_only():
    user = CapabilitySet.create(
        _principal(PrincipalType.USER, "42"),
        {Capability.PROVIDER_EXECUTE, Capability.TOOL_EXECUTE_STANDARD, Capability.SECRET_MANAGE},
    )
    grant = derive_execution_capabilities(
        user_grant=user,
        bot_principal=_principal(PrincipalType.BOT, "11"),
        bot_scope="standard",
        requested={Capability.PROVIDER_EXECUTE, Capability.TOOL_EXECUTE_STANDARD, Capability.SECRET_MANAGE},
        execution_id="exec-1",
    )
    assert grant.principal.kind is PrincipalType.EXECUTION
    assert grant.capabilities == {Capability.PROVIDER_EXECUTE, Capability.TOOL_EXECUTE_STANDARD}


def test_unknown_bot_scope_yields_empty_grant():
    user = CapabilitySet.create(_principal(PrincipalType.USER, "42"), set(Capability))
    grant = derive_execution_capabilities(
        user_grant=user, bot_principal=_principal(PrincipalType.BOT, "11"), bot_scope="root",
        requested={Capability.PROVIDER_EXECUTE}, execution_id="exec-1",
    )
    assert grant.capabilities == frozenset()


def test_cross_tenant_execution_is_rejected():
    user = CapabilitySet.create(_principal(PrincipalType.USER, "42", 7), {Capability.PROVIDER_EXECUTE})
    with pytest.raises(PermissionError, match="cross-tenant"):
        derive_execution_capabilities(
            user_grant=user, bot_principal=_principal(PrincipalType.BOT, "11", 8), bot_scope="standard",
            requested={Capability.PROVIDER_EXECUTE}, execution_id="exec-1",
        )


@pytest.mark.parametrize("kind,identifier,organization_id", [
    (PrincipalType.USER, "", 7),
    (PrincipalType.USER, "42", 0),
])
def test_principal_requires_explicit_identity_and_tenant(kind, identifier, organization_id):
    with pytest.raises(ValueError):
        Principal(kind, identifier, organization_id)
