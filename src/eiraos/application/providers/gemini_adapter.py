from typing import List, Dict, Any, AsyncIterator
import httpx
from eiraos.application.providers.base import AIProviderProtocol

class GeminiProviderAdapter:
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

    async def generate_chat_completion(
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
            response.raise_for_status()
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]

    async def stream_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        system_prompt: str | None = None
    ) -> AsyncIterator[str]:
        payload = self._convert_messages(messages, system_prompt)
        url = f"{self.base_url}/models/{model}:streamGenerateContent?alt=sse&key={self.api_key}"

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        import json
                        try:
                            chunk = json.loads(line[6:].strip())
                            candidates = chunk.get("candidates", [])
                            if candidates:
                                parts = candidates[0].get("content", {}).get("parts", [])
                                for p in parts:
                                    if "text" in p:
                                        yield p["text"]
                        except json.JSONDecodeError:
                            continue
