import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

from eiraos.application.provider_failure_isolation import IsolatedProviderFailure, ProviderFailureKind, ProviderFailureIsolation
from eiraos.application.providers.http import post_with_retry, retry_delay
from eiraos.application.providers.openai_adapter import OpenAIProviderAdapter


@pytest.mark.asyncio
async def test_transient_status_retries_then_returns_response():
    calls = 0
    sleeps = []

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(503 if calls == 1 else 200, json={"ok": True})

    async def sleep(delay):
        sleeps.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await post_with_retry(
            client, "https://provider.test", provider="test", max_attempts=2,
            backoff_seconds=0.25, sleep=sleep,
        )
    assert response.status_code == 200
    assert calls == 2 and sleeps == [0.25]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 500])
async def test_non_transient_status_is_never_retried(status):
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await post_with_retry(
            client, "https://provider.test", provider="test", max_attempts=3,
            sleep=lambda _delay: asyncio.sleep(0),
        )
    assert response.status_code == status and calls == 1


@pytest.mark.asyncio
async def test_connect_and_read_timeout_retry_is_bounded():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("private upstream detail", request=request)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert (await post_with_retry(
            client, "https://provider.test", provider="test", max_attempts=2,
            backoff_seconds=0, sleep=lambda _delay: asyncio.sleep(0),
        )).status_code == 200
    assert calls == 2


def test_retry_after_is_parsed_and_capped():
    request = httpx.Request("POST", "https://provider.test")
    assert retry_delay(httpx.Response(429, headers={"Retry-After": "30"}, request=request), 0.1, 2) == 2
    future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=30), usegmt=True)
    assert 1.9 <= retry_delay(httpx.Response(503, headers={"Retry-After": future}, request=request), 0.1, 2) <= 2


@pytest.mark.asyncio
async def test_retry_configuration_cannot_expand_unboundedly():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(200))) as client:
        with pytest.raises(ValueError, match="attempts"):
            await post_with_retry(client, "https://provider.test", provider="test", max_attempts=4)


@pytest.mark.asyncio
async def test_outer_deadline_cancels_retry_backoff():
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    adapter = OpenAIProviderAdapter("secret", transport=httpx.MockTransport(handler))
    with pytest.raises(IsolatedProviderFailure) as caught:
        await ProviderFailureIsolation().execute(
            adapter.complete([{"role": "user", "content": "hello"}], "gpt-4o"),
            timeout_seconds=0.01,
        )
    assert caught.value.kind is ProviderFailureKind.TIMEOUT
    assert calls == 1


def test_streaming_paths_do_not_use_completion_retry_helper():
    import inspect
    from eiraos.application.providers import anthropic_adapter, gemini_adapter, openai_adapter

    for adapter in (OpenAIProviderAdapter, anthropic_adapter.AnthropicProviderAdapter, gemini_adapter.GeminiProviderAdapter):
        assert "post_with_retry" in inspect.getsource(adapter.complete)
        assert "post_with_retry" not in inspect.getsource(adapter.stream)
