"""F4-01 canonical chat provider contract."""

from dataclasses import dataclass
from typing import Any, AsyncIterator, Mapping, Protocol, Sequence, runtime_checkable

ChatMessage = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("provider usage cannot be negative")

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class ProviderCompletion:
    text: str
    usage: ProviderUsage | None = None


@dataclass(frozen=True, slots=True)
class ProviderStreamEvent:
    text: str | None = None
    usage: ProviderUsage | None = None

    def __post_init__(self) -> None:
        if (self.text is None) == (self.usage is None):
            raise ValueError("stream event must contain exactly one payload")


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
