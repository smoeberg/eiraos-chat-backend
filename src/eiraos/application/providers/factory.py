from eiraos.application.providers.base import ChatProvider
from eiraos.application.providers.openai_adapter import OpenAIProviderAdapter
from eiraos.application.providers.anthropic_adapter import AnthropicProviderAdapter
from eiraos.application.providers.gemini_adapter import GeminiProviderAdapter
from eiraos.application.providers.governed import GovernedAIProvider


class AIProviderFactory:
    @staticmethod
    def get_provider(provider_name: str, api_key: str) -> ChatProvider:
        name = provider_name.lower()
        if name == "openai":
            provider = OpenAIProviderAdapter(api_key=api_key)
        elif name in ["anthropic", "claude"]:
            provider = AnthropicProviderAdapter(api_key=api_key)
            name = "anthropic"
        elif name in ["google", "gemini"]:
            provider = GeminiProviderAdapter(api_key=api_key)
            name = "google"
        else:
            raise ValueError(f"Unsupported AI provider: {provider_name}")
        return GovernedAIProvider(provider=provider, provider_name=name)
