import structlog
from typing import AsyncGenerator, Dict, Any, List
import httpx
from eiraos.application.providers.base import AIProviderProtocol

logger = structlog.get_logger()

class GeminiProviderAdapter(AIProviderProtocol):
    """
    Enterprise adapter for Google Gemini models (Generative Language API).
    """
    def __init__(self, api_key: str, default_model: str = "gemini-1.5-pro"):
        self.api_key = api_key
        self.default_model = default_model

    async def complete(self, prompt: str, system_prompt: str | None = None, model: str | None = None) -> str:
        model_name = model or self.default_model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.api_key}"
        
        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": f"System Instructions: {system_prompt}"}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload = {"contents": contents}

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]

    async def stream_complete(self, prompt: str, system_prompt: str | None = None, model: str | None = None) -> AsyncGenerator[str, None]:
        model_name = model or self.default_model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:streamGenerateContent?alt=sse&key={self.api_key}"
        
        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": f"System Instructions: {system_prompt}"}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload = {"contents": contents}

        async with httpx.AsyncClient() as client:
            async with client.stream("POST", url, json=payload, timeout=60.0) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        import json
                        try:
                            chunk = json.loads(line[6:])
                            text = chunk.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                            if text:
                                yield text
                        except Exception:
                            pass
