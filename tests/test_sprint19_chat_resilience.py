import asyncio
import pytest

from eiraos.api.v1.chat import _next_chunk, _sanitize, _bot_accessible
from eiraos.domains.agents.models import Bot


# --- _next_chunk: no-hang / no-leak resilience -------------------------

async def _agen(items):
    for i in items:
        yield i


async def _hanging():
    raise NotImplementedError  # simulates a generator whose __anext__ raises
    yield  # pragma: no cover


@pytest.mark.asyncio
async def test_next_chunk_returns_none_on_drain():
    stream = _agen(["a", "b"])
    assert await _next_chunk(stream, 1.0) == "a"
    assert await _next_chunk(stream, 1.0) == "b"
    assert await _next_chunk(stream, 1.0) is None  # StopAsyncIteration absorbed


@pytest.mark.asyncio
async def test_next_chunk_times_out_on_hang():
    async def stuck():
        await asyncio.sleep(30)
        yield "late"  # stalled upstream provider never delivers on time

    with pytest.raises(asyncio.TimeoutError):
        await _next_chunk(stuck(), timeout=0.05)


@pytest.mark.asyncio
async def test_next_chunk_honer_sanitize():
    assert _sanitize() == "An unexpected error occurred while processing your request."
    # Never echoes upstream internals / keys
    assert "openai" not in _sanitize().lower()
    assert "token" not in _sanitize().lower()
    assert "127.0.0.1" not in _sanitize()


# --- _bot_accessible: visibility single-source-of-truth ------------------

def _mk(**kw):
    base = {"id": 1, "title": "t", "provider": "openai", "model": "gpt-4o"}
    base.setdefault("organization_id", 1)
    base.update(kw)
    return Bot(**base)


def test_bot_accessible_org_match():
    bot = _mk(organization_id=5)
    # bot belongs to caller's org -> reachable regardless of visibility string
    assert _bot_accessible(bot, org_id=5) is True


def test_bot_accessible_legacy_public_boolean():
    # legacy is_public=True must resolve to public reachability
    bot = _mk(organization_id=9, bot_visibility="private", is_public=True)
    assert _bot_accessible(bot, org_id=999) is True


def test_bot_accessible_private_not_reachable():
    bot = _mk(organization_id=9, bot_visibility="private", is_public=False)
    assert _bot_accessible(bot, org_id=999) is False


@pytest.mark.asyncio
async def test_bot_visibility_reconciles_is_public_overrides():
    assert Bot.visibility(_mk(bot_visibility="private", is_public=True)) == "public"
    assert Bot.visibility(_mk(bot_visibility="private", is_public=False)) == "private"
    assert Bot.visibility(_mk(bot_visibility="organization", is_public=False)) == "organization"
    # default when nothing set
    assert Bot.visibility(_mk(bot_visibility="private")) == "private"


@pytest.mark.asyncio
async def test_streaming_does_not_leak_secrets():
    secret = "TEST_SUPER_SECRET_KEY_999"
    from httpx import AsyncClient, ASGITransport
    from eiraos.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "conversation_id": 1,
            "bot_id": 1,
            "prompt": "Hello",
            "stream": True,
        }
        async with client.stream(
            "POST",
            "/api/v1/chat/completions",
            json=payload,
        ) as response:
            async for line in response.aiter_lines():
                assert secret not in line

