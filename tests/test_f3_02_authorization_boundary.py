from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from eiraos.api.v1.auth import require_permission
from eiraos.application.authorization import (
    AuthorizationBoundary,
    AuthorizationDenied,
)
from eiraos.domains.governance.capabilities import Capability, PrincipalType


def _db_with_membership(role: str | None):
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = (
        None if role is None else MagicMock(role=role)
    )
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_current_database_membership_not_jwt_role_is_authoritative():
    identity = {"user_id": 2, "organization_id": 7, "role": "owner"}
    context = await AuthorizationBoundary(_db_with_membership("viewer")).authorize(
        identity=identity, capability=Capability.CONVERSATION_READ,
    )
    assert context.role == "viewer"
    with pytest.raises(AuthorizationDenied, match="capability_not_granted"):
        await AuthorizationBoundary(_db_with_membership("viewer")).authorize(
            identity=identity, capability=Capability.CONVERSATION_CREATE,
        )


@pytest.mark.asyncio
async def test_authorization_context_is_typed_and_tenant_bound():
    context = await AuthorizationBoundary(_db_with_membership("member")).authorize(
        identity={"user_id": 2, "organization_id": 7},
        capability=Capability.CONVERSATION_CREATE,
    )
    assert context.user.kind is PrincipalType.USER
    assert context.organization.kind is PrincipalType.ORGANIZATION
    assert context.user_id == 2 and context.organization_id == 7
    assert context.decision.allowed


@pytest.mark.asyncio
async def test_cross_tenant_resource_is_denied_before_grant():
    with pytest.raises(AuthorizationDenied) as exc:
        await AuthorizationBoundary(_db_with_membership("owner")).authorize(
            identity={"user_id": 2, "organization_id": 7},
            capability=Capability.ORGANIZATION_UPDATE,
            resource_organization_id=8,
        )
    assert exc.value.reason == "tenant_mismatch"


@pytest.mark.asyncio
async def test_zero_resource_tenant_does_not_fall_back_to_identity_tenant():
    with pytest.raises(AuthorizationDenied) as exc:
        await AuthorizationBoundary(_db_with_membership("owner")).authorize(
            identity={"user_id": 2, "organization_id": 7},
            capability=Capability.ORGANIZATION_UPDATE,
            resource_organization_id=0,
        )
    assert exc.value.reason == "tenant_mismatch"


@pytest.mark.asyncio
@pytest.mark.parametrize("identity,reason", [
    ({"user_id": None, "organization_id": 7}, "invalid_identity"),
    ({"user_id": 2, "organization_id": None}, "invalid_tenant"),
    ({"user_id": 0, "organization_id": 7}, "invalid_identity"),
])
async def test_invalid_identity_context_fails_before_database(identity, reason):
    db = AsyncMock()
    with pytest.raises(AuthorizationDenied) as exc:
        await AuthorizationBoundary(db).authorize(
            identity=identity, capability=Capability.CONVERSATION_READ,
        )
    assert exc.value.reason == reason
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_membership_fails_closed():
    with pytest.raises(AuthorizationDenied) as exc:
        await AuthorizationBoundary(_db_with_membership(None)).authorize(
            identity={"user_id": 2, "organization_id": 7},
            capability=Capability.CONVERSATION_READ,
        )
    assert exc.value.reason == "membership_not_found"


@pytest.mark.asyncio
async def test_unknown_capability_fails_closed_at_boundary():
    with pytest.raises(AuthorizationDenied) as exc:
        await AuthorizationBoundary(_db_with_membership("owner")).authorize(
            identity={"user_id": 2, "organization_id": 7}, capability="root:all",
        )
    assert exc.value.reason == "unknown_capability"


@pytest.mark.asyncio
async def test_fastapi_adapter_delegates_and_returns_authorized_identity():
    identity = {"user_id": 2, "organization_id": 7, "role": "viewer"}
    result = await require_permission("conversation:create")(
        current_user=identity, db=_db_with_membership("member"),
    )
    assert result is identity
    assert result["role"] == "member"
    assert result["authorization"].decision.capability is Capability.CONVERSATION_CREATE


@pytest.mark.asyncio
async def test_fastapi_adapter_does_not_leak_denial_reason():
    with pytest.raises(HTTPException) as exc:
        await require_permission("conversation:create")(
            current_user={"user_id": 2, "organization_id": 7},
            db=_db_with_membership("viewer"),
        )
    assert exc.value.status_code == 403
    assert "capability_not_granted" not in exc.value.detail


def test_chat_route_has_one_capability_dependency_not_parallel_route_gate():
    from eiraos.api.v1 import chat

    route = next(route for route in chat.router.routes if route.path == "/chat/completions")
    direct_calls = [dependency.call for dependency in route.dependant.dependencies]
    permission_calls = [
        call for call in direct_calls
        if "permission_dependency" in getattr(call, "__qualname__", "")
    ]
    assert len(permission_calls) == 1
    assert not route.dependencies
