from typing import AsyncIterator, Any

from eiraos.application.providers.base import AIProviderProtocol
from eiraos.application.providers.policy import authorize_provider_model


class GovernedAIProvider:
    """Execution-boundary guard around a concrete provider adapter.

    Provider/model authorization happens immediately before the upstream call,
    so callers cannot bypass the policy by constructing a provider directly
    through the factory and selecting an arbitrary model at execution time.
    """

    def __init__(self, provider: AIProviderProtocol, provider_name: str):
        self._provider = provider
        self._provider_name = provider_name

    def __repr__(self) -> str:
        return f"GovernedAIProvider(provider={self._provider_name!r}, configured=True)"

    async def generate_chat_completion(self, messages, model: str, temperature: float = 0.7,
                                       max_tokens: int = 1000, system_prompt: str | None = None) -> str:
        provider_name, authorized_model = authorize_provider_model(self._provider_name, model)
        # provider_name is normalized by the same policy that guards the call.
        if provider_name != self._provider_name:
            raise RuntimeError("Provider policy normalization mismatch")
        return await self._provider.generate_chat_completion(
            messages=messages,
            model=authorized_model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )

    async def stream_chat_completion(self, messages, model: str, temperature: float = 0.7,
                                     max_tokens: int = 1000, system_prompt: str | None = None) -> AsyncIterator[str]:
        provider_name, authorized_model = authorize_provider_model(self._provider_name, model)
        if provider_name != self._provider_name:
            raise RuntimeError("Provider policy normalization mismatch")
        stream = self._provider.stream_chat_completion(
            messages=messages,
            model=authorized_model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )
        async for chunk in stream:
            yield chunk
