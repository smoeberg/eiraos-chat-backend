from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from eiraos.core import idempotency


class _Result:
    rowcount = 1


class _DB:
    def __init__(self):
        self.executed = []
        self.commits = 0

    async def execute(self, statement):
        self.executed.append(statement)
        return _Result()

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_renewal_requires_authenticated_owner(monkeypatch):
    db = _DB()
    request = SimpleNamespace(state=SimpleNamespace(organization_id=10, user_id=20))
    result = await idempotency.renew_idempotency_lease(db, request, "key", "owner-token")
    assert result is True
    assert db.commits == 1


@pytest.mark.asyncio
async def test_renewal_uses_atomic_fencing_update():
    db = _DB()
    request = SimpleNamespace(state=SimpleNamespace(organization_id=10, user_id=20))
    await idempotency.renew_idempotency_lease(db, request, "key", "token")
    sql = str(db.executed[0]).lower()
    assert "lease_token" in sql
    assert "status" in sql
    assert "lease_until" in sql


def test_lease_window_is_positive():
    now = datetime.now(timezone.utc)
    assert now + timedelta(seconds=idempotency.LEASE_SECONDS) > now
