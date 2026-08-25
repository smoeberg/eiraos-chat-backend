import json

import httpx
import pytest

from eiraos.application.providers.anthropic_adapter import AnthropicProviderAdapter
from eiraos.application.providers.gemini_adapter import GeminiProviderAdapter
from eiraos.application.providers.openai_adapter import OpenAIProviderAdapter
from eiraos.core.exceptions import EiraOSException


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter,response_body,assert_request",
    [
        (
            OpenAIProviderAdapter("secret", base_url="https://openai.test/v1/", transport=None),
            {"choices": [{"message": {"content": "openai"}}]},
            lambda request, body: (
                request.url.path == "/v1/chat/completions"
                and request.headers["authorization"] == "Bearer secret"
                and body["messages"][0] == {"role": "system", "content": "rules"}
                and body["temperature"] == 0.2
                and body["max_tokens"] == 17
            ),
        ),
        (
            AnthropicProviderAdapter("secret", base_url="https://anthropic.test/v1/", transport=None),
            {"content": [{"type": "text", "text": "anthropic"}]},
            lambda request, body: (
                request.url.path == "/v1/messages"
                and request.headers["x-api-key"] == "secret"
                and body["system"] == "rules"
                and body["temperature"] == 0.2
                and body["max_tokens"] == 17
            ),
        ),
        (
            GeminiProviderAdapter("secret", base_url="https://gemini.test/v1beta/", transport=None),
            {"candidates": [{"content": {"parts": [{"text": "gemini"}]}}]},
            lambda request, body: (
                request.url.path == "/v1beta/models/model:generateContent"
                and request.url.query == b""
                and request.headers["x-goog-api-key"] == "secret"
                and body["systemInstruction"] == {"parts": [{"text": "rules"}]}
                and body["generationConfig"] == {"temperature": 0.2, "maxOutputTokens": 17}
            ),
        ),
    ],
)
async def test_completion_adapters_map_canonical_request(adapter, response_body, assert_request):
    seen = {}

    def handler(request):
        body = json.loads(request.content)
        seen["valid"] = assert_request(request, body)
        return httpx.Response(200, json=response_body)

    adapter._transport = _transport(handler)
    result = await adapter.complete(
        [{"role": "user", "content": "hello"}],
        "model",
        temperature=0.2,
        max_tokens=17,
        system_prompt="rules",
    )

    assert seen == {"valid": True}
    assert result in {"openai", "anthropic", "gemini"}


STREAM_CASES = (
    (
        OpenAIProviderAdapter,
        'data: {bad}\n\ndata: {"choices":[{"delta":{"content":"A"}}]}\n\ndata: [DONE]\n\n',
    ),
    (
        AnthropicProviderAdapter,
        'data: {bad}\n\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"A"}}\n\n',
    ),
    (
        GeminiProviderAdapter,
        'data: {bad}\n\ndata: {"candidates":[{"content":{"parts":[{"text":"A"}]}}]}\n\n',
    ),
)


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_type,sse", STREAM_CASES)
async def test_stream_adapters_emit_text_and_skip_malformed_chunks(adapter_type, sse):
    adapter = adapter_type("secret", base_url="https://provider.test/v1/", transport=_transport(
        lambda request: httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
    ))

    chunks = [chunk async for chunk in adapter.stream([], "model")]

    assert chunks == ["A"]


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_type", [OpenAIProviderAdapter, AnthropicProviderAdapter, GeminiProviderAdapter])
@pytest.mark.parametrize("streaming", [False, True])
async def test_all_adapters_normalize_http_failures(adapter_type, streaming):
    adapter = adapter_type("secret", transport=_transport(lambda request: httpx.Response(429, json={"secret": "do not leak"})))

    with pytest.raises(EiraOSException) as caught:
        if streaming:
            _ = [chunk async for chunk in adapter.stream([], "model")]
        else:
            await adapter.complete([], "model")

    assert caught.value.status_code == 502
    assert caught.value.title == "Upstream request failed"
    assert "secret" not in caught.value.detail
    assert "do not leak" not in caught.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_type", [OpenAIProviderAdapter, AnthropicProviderAdapter, GeminiProviderAdapter])
async def test_all_adapters_normalize_invalid_completion_json(adapter_type):
    adapter = adapter_type("secret", transport=_transport(lambda request: httpx.Response(200, text="not-json")))

    with pytest.raises(EiraOSException) as caught:
        await adapter.complete([], "model")

    assert caught.value.status_code == 502
    assert caught.value.title == "Upstream request failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_type", [OpenAIProviderAdapter, AnthropicProviderAdapter, GeminiProviderAdapter])
@pytest.mark.parametrize("streaming", [False, True])
async def test_all_adapters_normalize_transport_failures(adapter_type, streaming):
    def unavailable(request):
        raise httpx.ConnectError("credential-bearing transport detail", request=request)

    adapter = adapter_type("secret", transport=_transport(unavailable))

    with pytest.raises(EiraOSException) as caught:
        if streaming:
            _ = [chunk async for chunk in adapter.stream([], "model")]
        else:
            await adapter.complete([], "model")

    assert caught.value.status_code == 502
    assert caught.value.detail.endswith("request failed.")
    assert "credential" not in caught.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_type,sse",
    [
        (OpenAIProviderAdapter, 'data: {"error":{"message":"internal"}}\n\n'),
        (AnthropicProviderAdapter, 'data: {"type":"error","error":{"message":"internal"}}\n\n'),
        (GeminiProviderAdapter, 'data: {"error":{"message":"internal"}}\n\n'),
    ],
)
async def test_provider_reported_stream_errors_fail_closed(adapter_type, sse):
    adapter = adapter_type("secret", transport=_transport(
        lambda request: httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
    ))

    with pytest.raises(EiraOSException) as caught:
        _ = [chunk async for chunk in adapter.stream([], "model")]

    assert caught.value.status_code == 502
    assert "internal" not in caught.value.detail
