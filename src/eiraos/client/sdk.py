import httpx
from typing import AsyncGenerator, Dict, Any, List

class EiraOSClient:
    """
    Official asynchronous Python SDK for EiraOS Chat & AI Backend.
    Enables Windows App, mobile apps, and microservices to interface seamlessly with FastAPI.
    """
    def __init__(self, base_url: str = "http://localhost:8000/api/v1"):
        self.base_url = base_url
        self.token: str | None = None
        self.organization_id: int | None = None

    def set_auth_token(self, token: str):
        self.token = token

    def set_organization(self, org_id: int):
        self.organization_id = org_id

    def _get_headers(self) -> Dict[str, str]:
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.organization_id:
            headers["X-Organization-ID"] = str(self.organization_id)
        return headers

    async def login(self, username: str, password: str) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/auth/login",
                data={"username": username, "password": password}
            )
            response.raise_for_status()
            data = response.json()
            self.token = data.get("access_token")
            return data

    async def stream_chat(self, prompt: str, bot_id: int | None = None) -> AsyncGenerator[str, None]:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json={"prompt": prompt, "bot_id": bot_id, "stream": True},
                headers=self._get_headers(),
                timeout=60.0
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        yield line

    async def search_documents(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/documents/search",
                json={"query": query, "limit": limit},
                headers=self._get_headers()
            )
            response.raise_for_status()
            return response.json()
