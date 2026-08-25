from typing import List, Dict, Any, AsyncIterator
import json
import logging
import httpx
from eiraos.application.providers.base import ProviderCapabilities
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

    def __init__(self, api_key: str, base_url: str = "https://generativelanguage.googleapis.com/v1beta"):
        self.api_key = api_key
        self.base_url = base_url

    def _convert_messages(self, messages: List[Dict[str, Any]], system_prompt: str | None = None) -> Dict[str, Any]:
        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": f"[System Instruction: {system_prompt}]"}]})
        for m in messages:
            role = "model" if m["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
        return {"contents": contents}

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        system_prompt: str | None = None
    ) -> str:
        payload = self._convert_messages(messages, system_prompt)
        url = f"{self.base_url}/models/{model}:generateContent?key={self.api_key}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload)
            try:
                response.raise_for_status()
                return _unpack_gemini_text(response.json())
            except httpx.HTTPError:
                raise EiraOSException(title="Upstream request failed", detail="Gemini request failed.", status_code=502)

    async def stream(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        system_prompt: str | None = None
    ) -> AsyncIterator[str]:
        payload = self._convert_messages(messages, system_prompt)
        url = f"{self.base_url}/models/{model}:streamGenerateContent?alt=sse&key={self.api_key}"

        corrupt_chunks = 0
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, json=payload) as response:
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
                    candidates = chunk.get("candidates", [])
                    if candidates and isinstance(candidates[0], dict):
                        parts = candidates[0].get("content", {}).get("parts", [])
                        for p in parts:
                            if isinstance(p, dict) and "text" in p:
                                yield p["text"]

    def models(self) -> tuple[str, ...]:
        return self.MODEL_CATALOG

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(streaming=True)

    async def generate_chat_completion(self, *args, **kwargs) -> str:
        return await self.complete(*args, **kwargs)

    async def stream_chat_completion(self, *args, **kwargs) -> AsyncIterator[str]:
        async for chunk in self.stream(*args, **kwargs):
            yield chunk
