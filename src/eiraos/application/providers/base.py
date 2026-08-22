from typing import Protocol, AsyncGenerator, List, Dict, Any, runtime_checkable

@runtime_checkable
class AIProvider(Protocol):
    """
    Asynchronous AI Provider Protocol defining standard interface for OpenAI, Anthropic, Gemini, etc.
    Enables clean provider swapping and multi-provider architecture without tight coupling.
    """

    async def generate_chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        system_prompt: str | None = None
    ) -> str:
        """Generate a complete non-streaming chat response."""
        ...

    async def stream_chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        system_prompt: str | None = None
    ) -> AsyncGenerator[str, None]:
        """Stream a chat response token-by-token (SSE ready)."""
        ...
