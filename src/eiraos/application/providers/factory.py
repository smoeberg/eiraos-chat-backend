from eiraos.application.providers.base import AIProviderProtocol
from eiraos.application.providers.openai_adapter import OpenAIProviderAdapter
from eiraos.application.providers.anthropic_adapter import AnthropicProviderAdapter
from eiraos.application.providers.gemini_adapter import GeminiProviderAdapter

class AIProviderFactory:
    @staticmethod
    def get_provider(provider_name: str, api_key: str) -> AIProviderProtocol:
        name = provider_name.lower()
        if name == "openai":
            return OpenAIProviderAdapter(api_key=api_key)
        elif name in ["anthropic", "claude"]:
            return AnthropicProviderAdapter(api_key=api_key)
        elif name in ["google", "gemini"]:
            return GeminiProviderAdapter(api_key=api_key)
        else:
            raise ValueError(f"Unsupported AI provider: {provider_name}")
