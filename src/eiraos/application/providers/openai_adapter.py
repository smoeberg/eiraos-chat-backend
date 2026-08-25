from typing import List, Dict, Any, AsyncIterator
import json
import logging
import httpx
from eiraos.application.providers.base import (
    ProviderCapabilities, ProviderCompletion, ProviderStreamEvent, ProviderUsage,
)
from eiraos.application.providers.http import decode_completion, normalized_base_url, post_with_retry, upstream_failure
from eiraos.core.exceptions import EiraOSException

logger = logging.getLogger("eiraos.providers.openai")


def _unpack_message(data) -> str:
    """Extract assistant content defensively; raise sanitized EiraOSException, never raw Index/KeyError."""
    if not isinstance(data, dict):
        raise EiraOSException(title="Bad upstream payload", detail="Provider returned a non-JSON object.", status_code=502)
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise EiraOSException(title="Bad upstream payload", detail="Provider response had no choices.", status_code=502)
    message = choices[0]
    if not isinstance(message, dict):
        raise EiraOSException(title="Bad upstream payload", detail="Provider completion had no message field.", status_code=502)
    msg = message.get("message")
    if not isinstance(msg, dict):
        raise EiraOSException(title="Bad upstream payload", detail="Provider completion had no message field.", status_code=502)
    content = msg.get("content")
    return content if isinstance(content, str) else ""


def _usage(data, input_key: str, output_key: str, *, total_key: str | None = None) -> ProviderUsage | None:
    if not isinstance(data, dict):
        return None
    input_tokens, output_tokens = data.get(input_key), data.get(output_key)
    if type(input_tokens) is not int or type(output_tokens) is not int:
        return None
    if total_key is not None:
        total = data.get(total_key)
        if type(total) is not int or total != input_tokens + output_tokens:
            return None
    try:
        return ProviderUsage(input_tokens, output_tokens)
    except ValueError:
        return None


class OpenAIProviderAdapter:
    MODEL_CATALOG = ("gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini")

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1", *, transport=None):
        self.api_key = api_key
        self.base_url = normalized_base_url(base_url)
        self._transport = transport

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        system_prompt: str | None = None
    ) -> str:
        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})
        formatted_messages.extend(messages)

        try:
            async with self._client(60.0) as client:
                response = await post_with_retry(
                    client,
                    f"{self.base_url}/chat/completions",
                    provider="OpenAI",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": formatted_messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "stream": False
                    }
                )
                return decode_completion(response, "OpenAI", _unpack_message)
        except httpx.HTTPError as exc:
            raise upstream_failure("OpenAI", exc) from exc

    async def complete_with_usage(self, *args, **kwargs) -> ProviderCompletion:
        messages = kwargs.get("messages", args[0] if args else None)
        model = kwargs.get("model", args[1] if len(args) > 1 else None)
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens", 1000)
        system_prompt = kwargs.get("system_prompt")
        formatted = ([{"role": "system", "content": system_prompt}] if system_prompt else [])
        formatted.extend(messages)
        try:
            async with self._client(60.0) as client:
                response = await post_with_retry(
                    client, f"{self.base_url}/chat/completions", provider="OpenAI",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={"model": model, "messages": formatted, "temperature": temperature,
                          "max_tokens": max_tokens, "stream": False},
                )
                data = response.json()
                usage = data.get("usage") if isinstance(data, dict) else None
                parsed = _usage(
                    usage, "prompt_tokens", "completion_tokens", total_key="total_tokens"
                )
                return ProviderCompletion(_unpack_message(data), parsed)
        except httpx.HTTPError as exc:
            raise upstream_failure("OpenAI", exc) from exc


    async def stream(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        system_prompt: str | None = None
    ) -> AsyncIterator[str]:
        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})
        formatted_messages.extend(messages)

        corrupt_chunks = 0
        try:
            async with self._client(120.0) as client:
                async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": formatted_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True
                }
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            if chunk.get("error"):
                                raise upstream_failure("OpenAI")
                            delta = chunk["choices"][0]["delta"]
                            if "content" in delta and delta["content"]:
                                yield delta["content"]
                        except EiraOSException:
                            raise
                        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                            corrupt_chunks += 1
                            logger.warning("openai_stream_skipped_corrupt_chunk", extra={"skip_chunk_count": corrupt_chunks})
                            continue
        except httpx.HTTPError as exc:
            raise upstream_failure("OpenAI", exc) from exc

    async def stream_with_usage(self, *args, **kwargs):
        messages = kwargs.get("messages", args[0] if args else None)
        system_prompt = kwargs.get("system_prompt")
        formatted = ([{"role": "system", "content": system_prompt}] if system_prompt else [])
        formatted.extend(messages)
        payload = {
            "model": kwargs.get("model", args[1] if len(args) > 1 else None),
            "messages": formatted, "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 1000), "stream": True,
            "stream_options": {"include_usage": True},
        }
        async with self._client(120.0) as client:
            async with client.stream(
                "POST", f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"}, json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: ") or line[6:].strip() == "[DONE]":
                        continue
                    try:
                        data = json.loads(line[6:].strip())
                    except json.JSONDecodeError:
                        continue
                    usage = _usage(data.get("usage"), "prompt_tokens", "completion_tokens",
                                   total_key="total_tokens")
                    if usage is not None:
                        yield ProviderStreamEvent(usage=usage)
                    choices = data.get("choices") or []
                    if choices and isinstance(choices[0], dict):
                        text = (choices[0].get("delta") or {}).get("content")
                        if text:
                            yield ProviderStreamEvent(text=text)

    def models(self) -> tuple[str, ...]:
        return self.MODEL_CATALOG

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(streaming=True)

    async def generate_chat_completion(self, *args, **kwargs) -> str:
        return await self.complete(*args, **kwargs)

    async def stream_chat_completion(self, *args, **kwargs) -> AsyncIterator[str]:
        async for chunk in self.stream(*args, **kwargs):
            yield chunk
