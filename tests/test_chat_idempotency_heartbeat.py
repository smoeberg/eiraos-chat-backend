import asyncio
from types import SimpleNamespace

import pytest

from eiraos.api.v1 import chat


@pytest.mark.asyncio
async def test_lease_heartbeat_renews_until_cancelled(monkeypatch):
    calls = 0

    async def renew(_db, _request, _key, _token):
        nonlocal calls
        calls += 1
        return True

    monkeypatch.setattr(chat.idempotency, "LEASE_RENEWAL_SECONDS", 0.01)
    monkeypatch.setattr(chat.idempotency, "LEASE_SECONDS", 1)
    monkeypatch.setattr(chat.idempotency, "renew_idempotency_lease", renew)

    lost = asyncio.Event()
    task = asyncio.create_task(chat._lease_heartbeat(SimpleNamespace(), SimpleNamespace(), "k", "t", lost))
    await asyncio.sleep(0.035)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls >= 2
    assert not lost.is_set()


@pytest.mark.asyncio
async def test_lease_heartbeat_fails_closed_when_renewal_is_rejected(monkeypatch):
    async def renew(_db, _request, _key, _token):
        return False

    monkeypatch.setattr(chat.idempotency, "LEASE_RENEWAL_SECONDS", 0.01)
    monkeypatch.setattr(chat.idempotency, "LEASE_SECONDS", 1)
    monkeypatch.setattr(chat.idempotency, "renew_idempotency_lease", renew)

    lost = asyncio.Event()
    await chat._lease_heartbeat(SimpleNamespace(), SimpleNamespace(), "k", "t", lost)

    assert lost.is_set()


@pytest.mark.asyncio
async def test_start_and_stop_heartbeat_without_idempotency_are_noops():
    task, lost = await chat._start_lease_heartbeat(SimpleNamespace(), SimpleNamespace(), None, None)
    assert task is None
    assert lost is None
    assert await chat._stop_lease_heartbeat(task, lost) is True
