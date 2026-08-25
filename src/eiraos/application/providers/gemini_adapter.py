from typing import List, Dict, Any, AsyncIterator
import json
import logging
import httpx
from eiraos.application.providers.base import ProviderCapabilities
from eiraos.application.providers.http import decode_completion, normalized_base_url, post_with_retry, upstream_failure
from eiraos.core.exceptions import EiraOSException

logger = logging.getLogger("eiraos.providers.gemini")


def _unpack_gemini_text(data) -> str:
    """Extract candidate text defensively; raise sanitized EiraOSException, never raw Index/KeyError."""
    if not isinstance(data, dict):
        raise EiraOSException(title="Bad upstream payload", detail="Provider returned a non-JSON object.", status_code=502)
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise EiraOSException(title="Bad upstream payload", detail="Provider response had no candidates.", status_code=502)
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise EiraOSException(title="Bad upstream payload", detail="Provider response had a malformed candidate.", status_code=502)
    content = candidate.get("content") or {}
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list) or not parts:
        raise EiraOSException(title="Bad upstream payload", detail="Provider response had no text parts.", status_code=502)
    text = parts[0].get("text") if isinstance(parts[0], dict) else None
    return text if isinstance(text, str) else ""


class GeminiProviderAdapter:
    MODEL_CATALOG = ("gemini-1.5-pro", "gemini-1.5-flash")

    def __init__(self, api_key: str, base_url: str = "https://generativelanguage.googleapis.com/v1beta", *, transport=None):
        self.api_key = api_key
        self.base_url = normalized_base_url(base_url)
        self._transport = transport

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    def _convert_messages(self, messages: List[Dict[str, Any]], system_prompt: str | None = None) -> Dict[str, Any]:
        contents = []
        for m in messages:
            role = "model" if m["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
        payload = {"contents": contents}
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
        return payload

    def _payload(self, messages, temperature, max_tokens, system_prompt):
        payload = self._convert_messages(messages, system_prompt)
        payload["generationConfig"] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        return payload

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        system_prompt: str | None = None
    ) -> str:
        payload = self._payload(messages, temperature, max_tokens, system_prompt)
        url = f"{self.base_url}/models/{model}:generateContent"

        try:
            async with self._client(60.0) as client:
                response = await post_with_retry(
                    client, url, provider="Gemini",
                    headers={"x-goog-api-key": self.api_key}, json=payload,
                )
                return decode_completion(response, "Gemini", _unpack_gemini_text)
        except httpx.HTTPError as exc:
            raise upstream_failure("Gemini", exc) from exc

    async def stream(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        system_prompt: str | None = None
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, temperature, max_tokens, system_prompt)
        url = f"{self.base_url}/models/{model}:streamGenerateContent?alt=sse"

        corrupt_chunks = 0
        try:
            async with self._client(120.0) as client:
                async with client.stream("POST", url, headers={"x-goog-api-key": self.api_key}, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        try:
                            chunk = json.loads(line[6:].strip())
                        except json.JSONDecodeError:
                            corrupt_chunks += 1
                            logger.warning("gemini_stream_skipped_corrupt_chunk", extra={"skip_chunk_count": corrupt_chunks})
                            continue
                        if chunk.get("error"):
                            raise upstream_failure("Gemini")
                        candidates = chunk.get("candidates", [])
                        if candidates and isinstance(candidates[0], dict):
                            parts = candidates[0].get("content", {}).get("parts", [])
                            for part in parts:
                                text = part.get("text") if isinstance(part, dict) else None
                                if text:
                                    yield text
        except httpx.HTTPError as exc:
            raise upstream_failure("Gemini", exc) from exc

    def models(self) -> tuple[str, ...]:
        return self.MODEL_CATALOG

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(streaming=True)

    async def generate_chat_completion(self, *args, **kwargs) -> str:
        return await self.complete(*args, **kwargs)

    async def stream_chat_completion(self, *args, **kwargs) -> AsyncIterator[str]:
        async for chunk in self.stream(*args, **kwargs):
            yield chunk
