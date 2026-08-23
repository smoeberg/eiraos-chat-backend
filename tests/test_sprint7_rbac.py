"""Sprint 7: RBAC permission-matrix consistency + require_permission enforcement."""
import anyio
from fastapi import HTTPException

from eiraos.api.v1.auth import ROLE_PERMISSIONS, require_permission

ALL_ROLES = ("owner", "admin", "member", "viewer")
ALL_PERMISSIONS = {
    "organization:read", "organization:update", "member:invite", "member:remove",
    "member:manage", "bot:read", "bot:create", "bot:update", "bot:delete",
    "document:read", "document:upload", "document:delete",
    "conversation:read", "conversation:create", "conversation:delete",
    "usage:read", "secret:manage",
}


def test_role_permission_keys_valid():
    for role in ALL_ROLES:
        assert role in ROLE_PERMISSIONS, f"missing role {role}"
        unknown = set(ROLE_PERMISSIONS[role]) - ALL_PERMISSIONS
        assert not unknown, f"role {role} references unknown permissions {unknown}"


def test_every_permission_assigned_to_at_least_one_role():
    assigned = set().union(*ROLE_PERMISSIONS.values())
    unassigned = ALL_PERMISSIONS - assigned
    assert not unassigned, f"orphan permissions never granted: {unassigned}"


def test_owner_has_superset_of_admin():
    owner = set(ROLE_PERMISSIONS["owner"])
    admin = set(ROLE_PERMISSIONS["admin"])
    assert owner >= admin, "owner must be a superset of admin"


def test_admin_has_superset_of_member():
    admin = set(ROLE_PERMISSIONS["admin"])
    member = set(ROLE_PERMISSIONS["member"])
    assert admin >= member, "admin must be a superset of member"


def test_member_has_superset_of_viewer():
    member = set(ROLE_PERMISSIONS["member"])
    viewer = set(ROLE_PERMISSIONS["viewer"])
    assert member >= viewer, "member must be a superset of viewer"


def test_owner_has_privileged_permissions():
    owner = set(ROLE_PERMISSIONS["owner"])
    assert "secret:manage" in owner
    assert "member:manage" in owner
    assert "organization:update" in owner


def test_require_permission_allows_holder():
    async def _run():
        dep = require_permission("bot:create")
        user = {"role": "admin", "organization_id": 1, "user_id": 2}
        # call the inner dependency directly with an explicit current_user
        result = await dep.__call__(current_user=user)
        assert result == user

    anyio.run(_run)


def test_require_permission_denies_non_holder():
    async def _run():
        dep = require_permission("bot:create")
        user = {"role": "viewer", "organization_id": 1, "user_id": 2}
        try:
            await dep.__call__(current_user=user)
            raise AssertionError("expected 403 for missing permission")
        except HTTPException as e:
            assert e.status_code == 403

    anyio.run(_run)


def test_bot_write_gated_endpoints():
    """bot:update / bot:delete are anticipated-only today (no endpoints yet)."""
    # Guard: every endpoint that mutates a bot must use require_permission.
    import inspect
    import eiraos.api.v1.bots as bots
    src = inspect.getsource(bots)
    # create path must be gated (already is)
    assert "require_permission(\"bot:create\")" in src
