from typing import List, Dict, Any, AsyncIterator
import json
import logging
import httpx
from eiraos.application.providers.base import AIProviderProtocol
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


class OpenAIProviderAdapter:
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.base_url = base_url

    async def generate_chat_completion(
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

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": formatted_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": False
                }
            )
            try:
                response.raise_for_status()
                return _unpack_message(response.json())
            except httpx.HTTPError as e:
                status_code = e.response.status_code if e.response is not None else 502
                raise EiraOSException(title="Upstream request failed", detail=f"Completion request failed (HTTP {status_code}).", status_code=502) from e

    async def generate_structured_output(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        schema_name: str,
        schema: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Request strict JSON-schema output and return only validated JSON data."""
        if not schema_name or not schema:
            raise ValueError("schema_name and schema are required")

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": 0,
                        "stream": False,
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {
                                "name": schema_name,
                                "strict": True,
                                "schema": schema,
                            },
                        },
                    },
                )
                response.raise_for_status()
                data = response.json()
                content = _unpack_message(data)
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise ValueError("Structured provider output was not an object")
                return parsed
            except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise EiraOSException(
                    title="Structured extraction failed",
                    detail="The provider returned an invalid or unusable structured response.",
                    status_code=502,
                ) from exc

    async def stream_chat_completion(
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
        async with httpx.AsyncClient(timeout=120.0) as client:
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
                        delta = chunk["choices"][0]["delta"]
                        if "content" in delta and delta["content"]:
                            yield delta["content"]
                    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                        corrupt_chunks += 1
                        logger.warning("openai_stream_skipped_corrupt_chunk", extra={"skip_chunk_count": corrupt_chunks})
                        continue
