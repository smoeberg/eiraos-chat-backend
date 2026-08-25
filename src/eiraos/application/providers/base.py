"""F4-01 canonical chat provider contract."""

from dataclasses import dataclass
from typing import Any, AsyncIterator, Mapping, Protocol, Sequence, runtime_checkable

ChatMessage = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    streaming: bool
    vision: bool = False
    tools: bool = False
    structured_output: bool = False
    reasoning: bool = False
    embeddings: bool = False


@runtime_checkable
class ChatProvider(Protocol):
    async def complete(
        self,
        messages: Sequence[ChatMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        system_prompt: str | None = None,
    ) -> str: ...

    def stream(
        self,
        messages: Sequence[ChatMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        system_prompt: str | None = None,
    ) -> AsyncIterator[str]: ...

    def models(self) -> tuple[str, ...]: ...

    def capabilities(self) -> ProviderCapabilities: ...


# Import compatibility only. New application code uses ChatProvider.
AIProviderProtocol = ChatProvider
