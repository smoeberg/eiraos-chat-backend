import structlog
from typing import AsyncGenerator, Dict, Any, List
import httpx
from eiraos.application.providers.base import AIProviderProtocol

logger = structlog.get_logger()

class AnthropicProviderAdapter(AIProviderProtocol):
    """
    Enterprise adapter for Anthropic Claude models (Messages API).
    """
    def __init__(self, api_key: str, default_model: str = "claude-3-5-sonnet-20241022"):
        self.api_key = api_key
        self.default_model = default_model
        self.base_url = "https://api.anthropic.com/v1/messages"

    async def complete(self, prompt: str, system_prompt: str | None = None, model: str | None = None) -> str:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        messages = [{"role": "user", "content": prompt}]
        payload: Dict[str, Any] = {
            "model": model or self.default_model,
            "max_tokens": 4096,
            "messages": messages
        }
        if system_prompt:
            payload["system"] = system_prompt

        async with httpx.AsyncClient() as client:
            response = await client.post(self.base_url, json=payload, headers=headers, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"]

    async def stream_complete(self, prompt: str, system_prompt: str | None = None, model: str | None = None) -> AsyncGenerator[str, None]:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        messages = [{"role": "user", "content": prompt}]
        payload: Dict[str, Any] = {
            "model": model or self.default_model,
            "max_tokens": 4096,
            "messages": messages,
            "stream": True
        }
        if system_prompt:
            payload["system"] = system_prompt

        async with httpx.AsyncClient() as client:
            async with client.stream("POST", self.base_url, json=payload, headers=headers, timeout=60.0) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        import json
                        try:
                            chunk = json.loads(line[6:])
                            if chunk.get("type") == "content_block_delta":
                                yield chunk.get("delta", {}).get("text", "")
                        except Exception:
                            pass
