import dataclasses
import inspect

import pytest

from eiraos.application.providers.anthropic_adapter import AnthropicProviderAdapter
from eiraos.application.providers.base import ChatProvider, ProviderCapabilities
from eiraos.application.providers.factory import AIProviderFactory
from eiraos.application.providers.gemini_adapter import GeminiProviderAdapter
from eiraos.application.providers.governed import GovernedAIProvider
from eiraos.application.providers.openai_adapter import OpenAIProviderAdapter
from eiraos.application.providers.policy import DEFAULT_PROVIDER_MODELS


ADAPTERS = (
    ("openai", OpenAIProviderAdapter),
    ("anthropic", AnthropicProviderAdapter),
    ("google", GeminiProviderAdapter),
)


def test_canonical_protocol_has_exact_f4_01_surface():
    public = {
        name for name, value in inspect.getmembers(ChatProvider)
        if callable(value) and not name.startswith("_")
    }
    assert public == {"complete", "stream", "models", "capabilities"}


@pytest.mark.parametrize("provider_name,adapter_type", ADAPTERS)
def test_every_adapter_implements_runtime_contract(provider_name, adapter_type):
    adapter = adapter_type(api_key="sentinel")
    assert isinstance(adapter, ChatProvider)
    assert adapter.models() == tuple(adapter.models())
    assert len(adapter.models()) == len(set(adapter.models()))
    assert set(adapter.models()) == set(DEFAULT_PROVIDER_MODELS[provider_name])
    assert adapter.capabilities() == ProviderCapabilities(streaming=True)


def test_capabilities_are_immutable_and_fail_closed_by_default():
    capabilities = ProviderCapabilities(streaming=True)
    assert not capabilities.vision
    assert not capabilities.tools
    assert not capabilities.structured_output
    assert not capabilities.reasoning
    assert not capabilities.embeddings
    with pytest.raises(dataclasses.FrozenInstanceError):
        capabilities.tools = True


@pytest.mark.parametrize("provider_name", ["openai", "anthropic", "google"])
def test_factory_returns_governed_chat_provider(provider_name):
    provider = AIProviderFactory.get_provider(provider_name, "sentinel")
    assert isinstance(provider, GovernedAIProvider)
    assert isinstance(provider, ChatProvider)
    assert provider.models()
    assert provider.capabilities().streaming


def test_governed_catalog_is_intersection_with_server_policy(monkeypatch):
    monkeypatch.setenv("EIRAOS_ALLOWED_MODELS_OPENAI", "gpt-4o-mini,not-in-adapter")
    provider = AIProviderFactory.get_provider("openai", "sentinel")
    assert provider.models() == ("gpt-4o-mini",)


def test_application_uses_only_canonical_execution_methods():
    from eiraos.api.v1 import chat
    from eiraos.application import business_features

    chat_source = inspect.getsource(chat)
    verification_source = inspect.getsource(business_features.verify_answer)
    assert "provider.complete(" in chat_source
    assert "provider.stream(" in chat_source
    assert "verifier.complete(" in verification_source
    assert "generate_chat_completion(" not in chat_source
    assert "stream_chat_completion(" not in chat_source


def test_legacy_names_are_adapter_only_compatibility_aliases():
    for _, adapter_type in ADAPTERS:
        assert "generate_chat_completion" in adapter_type.__dict__
        assert "stream_chat_completion" in adapter_type.__dict__
    assert "generate_chat_completion" in GovernedAIProvider.__dict__
    assert "stream_chat_completion" in GovernedAIProvider.__dict__


@pytest.mark.asyncio
async def test_governed_legacy_aliases_preserve_positional_arguments():
    class FakeProvider:
        async def complete(self, messages, model, temperature=0.7, max_tokens=1000, system_prompt=None):
            return f"{model}:{len(messages)}"

        async def stream(self, messages, model, temperature=0.7, max_tokens=1000, system_prompt=None):
            yield model

        def models(self):
            return ("gpt-4o",)

        def capabilities(self):
            return ProviderCapabilities(streaming=True)

    governed = GovernedAIProvider(FakeProvider(), "openai")
    assert await governed.generate_chat_completion([], "gpt-4o") == "gpt-4o:0"
    assert [chunk async for chunk in governed.stream_chat_completion([], "gpt-4o")] == ["gpt-4o"]
