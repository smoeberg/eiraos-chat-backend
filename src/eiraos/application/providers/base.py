from typing import Protocol, AsyncIterator, List, Dict, Any, runtime_checkable

@runtime_checkable
class AIProviderProtocol(Protocol):
    async def generate_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        system_prompt: str | None = None
    ) -> str:
        """Generate a complete non-streaming chat response."""
        ...

    async def stream_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        system_prompt: str | None = None
    ) -> AsyncIterator[str]:
        """Stream a chat response token by token as SSE chunks."""
        ...
