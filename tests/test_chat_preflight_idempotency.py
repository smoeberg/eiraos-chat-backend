from unittest.mock import AsyncMock

import pytest

from eiraos.api.v1 import chat


@pytest.mark.asyncio
async def test_release_preflight_lease_completes_owned_lease(monkeypatch):
    complete = AsyncMock(return_value=True)
    monkeypatch.setattr(chat.idempotency, "complete_idempotency", complete)

    db = object()
    request = object()

    await chat._release_preflight_lease(db, request, "idem-1", "lease-1", 500)

    complete.assert_awaited_once_with(
        db,
        request,
        "idem-1",
        500,
        "failed",
        lease_token="lease-1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,token",
    [(None, "lease-1"), ("idem-1", None), (None, None)],
)
async def test_release_preflight_lease_is_noop_without_owned_lease(monkeypatch, key, token):
    complete = AsyncMock()
    monkeypatch.setattr(chat.idempotency, "complete_idempotency", complete)

    await chat._release_preflight_lease(object(), object(), key, token, 500)

    complete.assert_not_awaited()
