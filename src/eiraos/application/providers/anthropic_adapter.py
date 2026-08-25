from typing import List, Dict, Any, AsyncIterator
import json
import logging
import httpx
from eiraos.application.providers.base import ProviderCapabilities
from eiraos.application.providers.http import decode_completion, normalized_base_url, upstream_failure
from eiraos.core.exceptions import EiraOSException

logger = logging.getLogger("eiraos.providers.anthropic")


def _unpack_anthropic_message(data) -> str:
    """Extract assistant text defensively; raise sanitized EiraOSException, never raw Index/KeyError."""
    if not isinstance(data, dict):
        raise EiraOSException(title="Bad upstream payload", detail="Provider returned a non-JSON object.", status_code=502)
    content = data.get("content")
    if not isinstance(content, list) or not content:
        raise EiraOSException(title="Bad upstream payload", detail="Provider response had no content blocks.", status_code=502)
    block = content[0]
    if not isinstance(block, dict):
        raise EiraOSException(title="Bad upstream payload", detail="Provider response had a malformed content block.", status_code=502)
    text = block.get("text")
    return text if isinstance(text, str) else ""


class AnthropicProviderAdapter:
    MODEL_CATALOG = ("claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022")

    def __init__(self, api_key: str, base_url: str = "https://api.anthropic.com/v1", *, transport=None):
        self.api_key = api_key
        self.base_url = normalized_base_url(base_url)
        self._transport = transport

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    def _headers(self):
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        system_prompt: str | None = None
    ) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            payload["system"] = system_prompt

        try:
            async with self._client(60.0) as client:
                response = await client.post(f"{self.base_url}/messages", headers=self._headers(), json=payload)
                return decode_completion(response, "Anthropic", _unpack_anthropic_message)
        except httpx.HTTPError as exc:
            raise upstream_failure("Anthropic", exc) from exc

    async def stream(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        system_prompt: str | None = None
    ) -> AsyncIterator[str]:
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if system_prompt:
            payload["system"] = system_prompt

        corrupt_chunks = 0
        try:
            async with self._client(120.0) as client:
                async with client.stream("POST", f"{self.base_url}/messages", headers=self._headers(), json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        try:
                            event = json.loads(line[6:].strip())
                        except json.JSONDecodeError:
                            corrupt_chunks += 1
                            logger.warning("anthropic_stream_skipped_corrupt_chunk", extra={"skip_chunk_count": corrupt_chunks})
                            continue
                        if event.get("type") == "error":
                            raise upstream_failure("Anthropic")
                        if event.get("type") == "content_block_delta":
                            delta = event.get("delta", {})
                            text = delta.get("text") if delta.get("type") == "text_delta" else None
                            if text:
                                yield text
        except httpx.HTTPError as exc:
            raise upstream_failure("Anthropic", exc) from exc

    def models(self) -> tuple[str, ...]:
        return self.MODEL_CATALOG

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(streaming=True)

    async def generate_chat_completion(self, *args, **kwargs) -> str:
        return await self.complete(*args, **kwargs)

    async def stream_chat_completion(self, *args, **kwargs) -> AsyncIterator[str]:
        async for chunk in self.stream(*args, **kwargs):
            yield chunk
