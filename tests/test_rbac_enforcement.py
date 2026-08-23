import pytest
from fastapi import HTTPException

from eiraos.api.v1 import documents, conversations, chat, organizations, bots
from eiraos.api.v1.auth import require_permission


def _permissions_enforced(module) -> set:
    """Collect every permission string wired via require_permission on a router."""
    perms = set()
    for route in module.router.routes:
        dependant = getattr(route, "dependant", None)
        for d in (dependant.dependencies if dependant else []) or []:
            call = getattr(d, "call", None)
            for cell in (call.__closure__ or []) if call else []:
                try:
                    v = cell.cell_contents
                except ValueError:
                    continue
                if isinstance(v, str) and ":" in v:
                    perms.add(v)
    return perms


@pytest.mark.parametrize("module, permission", [
    (documents, "document:upload"),
    (documents, "document:read"),
    (conversations, "conversation:create"),
    (conversations, "conversation:read"),
    (conversations, "conversation:delete"),
    (chat, "conversation:create"),
    (organizations, "organization:read"),
    (bots, "bot:create"),
    (bots, "bot:read"),
])
def test_rbac_wired_on_endpoints(module, permission):
    enforced = _permissions_enforced(module)
    assert permission in enforced, (
        f"{module.__name__} does not enforce '{permission}' (found {enforced})"
    )


@pytest.mark.parametrize("role, permission, should_allow", [
    ("owner", "conversation:delete", True),
    ("admin", "conversation:delete", True),
    ("member", "document:upload", True),
    ("member", "document:delete", False),
    ("member", "bot:create", False),
    ("member", "conversation:delete", True),
    ("viewer", "document:upload", False),
    ("viewer", "conversation:create", False),
    ("viewer", "document:read", True),
    ("viewer", "conversation:delete", False),
])
def test_role_permission_matrix(role, permission, should_allow):
    async def run():
        dep = require_permission(permission)
        user = {"role": role, "user_id": 1, "email": "x@y.z"}
        if should_allow:
            assert await dep(user) == user
        else:
            with pytest.raises(HTTPException) as exc:
                await dep(user)
            assert exc.value.status_code == 403

    import asyncio
    asyncio.run(run())
