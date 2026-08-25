from typing import AsyncIterator

from eiraos.application.providers.base import (
    ChatProvider, ProviderCapabilities, ProviderCompletion, ProviderStreamEvent,
)
from eiraos.application.providers.policy import authorize_provider_model


class GovernedAIProvider:
    """Execution-boundary guard around a concrete provider adapter.

    Provider/model authorization happens immediately before the upstream call,
    so callers cannot bypass the policy by constructing a provider directly
    through the factory and selecting an arbitrary model at execution time.
    """

    def __init__(self, provider: ChatProvider, provider_name: str):
        self._provider = provider
        self._provider_name = provider_name

    def __repr__(self) -> str:
        return f"GovernedAIProvider(provider={self._provider_name!r}, configured=True)"

    async def complete(self, messages, model: str, temperature: float = 0.7,
                       max_tokens: int = 1000, system_prompt: str | None = None) -> str:
        provider_name, authorized_model = authorize_provider_model(self._provider_name, model)
        # provider_name is normalized by the same policy that guards the call.
        if provider_name != self._provider_name:
            raise RuntimeError("Provider policy normalization mismatch")
        return await self._provider.complete(
            messages=messages,
            model=authorized_model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )

    async def complete_with_usage(self, messages, model: str, temperature: float = 0.7,
                                  max_tokens: int = 1000, system_prompt: str | None = None):
        provider_name, authorized_model = authorize_provider_model(self._provider_name, model)
        if provider_name != self._provider_name:
            raise RuntimeError("Provider policy normalization mismatch")
        method = getattr(self._provider, "complete_with_usage", None)
        if method is None:
            text = await self._provider.complete(
                messages=messages, model=authorized_model, temperature=temperature,
                max_tokens=max_tokens, system_prompt=system_prompt,
            )
            return ProviderCompletion(text=text)
        return await method(
            messages=messages, model=authorized_model, temperature=temperature,
            max_tokens=max_tokens, system_prompt=system_prompt,
        )

    async def stream(self, messages, model: str, temperature: float = 0.7,
                     max_tokens: int = 1000, system_prompt: str | None = None) -> AsyncIterator[str]:
        provider_name, authorized_model = authorize_provider_model(self._provider_name, model)
        if provider_name != self._provider_name:
            raise RuntimeError("Provider policy normalization mismatch")
        stream = self._provider.stream(
            messages=messages,
            model=authorized_model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )
        async for chunk in stream:
            yield chunk

    async def stream_with_usage(self, messages, model: str, temperature: float = 0.7,
                                max_tokens: int = 1000, system_prompt: str | None = None):
        provider_name, authorized_model = authorize_provider_model(self._provider_name, model)
        if provider_name != self._provider_name:
            raise RuntimeError("Provider policy normalization mismatch")
        method = getattr(self._provider, "stream_with_usage", None)
        kwargs = dict(messages=messages, model=authorized_model, temperature=temperature,
                      max_tokens=max_tokens, system_prompt=system_prompt)
        if method is not None:
            async for event in method(**kwargs):
                yield event
            return
        async for text in self._provider.stream(**kwargs):
            yield ProviderStreamEvent(text=text)

    def models(self) -> tuple[str, ...]:
        authorized = []
        for model in self._provider.models():
            try:
                provider_name, normalized_model = authorize_provider_model(self._provider_name, model)
            except Exception:
                continue
            if provider_name == self._provider_name:
                authorized.append(normalized_model)
        return tuple(authorized)

    def capabilities(self) -> ProviderCapabilities:
        return self._provider.capabilities()

    async def generate_chat_completion(self, *args, **kwargs) -> str:
        return await self.complete(*args, **kwargs)

    async def stream_chat_completion(self, *args, **kwargs) -> AsyncIterator[str]:
        async for chunk in self.stream(*args, **kwargs):
            yield chunk
