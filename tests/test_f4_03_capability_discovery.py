from dataclasses import dataclass
from typing import Any

import pytest

from eiraos.application.providers.base import ProviderCapabilities
from eiraos.application.providers.capability_discovery import ProviderCapabilityDiscovery, ProviderModelMetadata


@dataclass
class FakeProvider:
    _models: tuple[str, ...] = ("model-a", "model-b")
    _capabilities: ProviderCapabilities = ProviderCapabilities(streaming=True)

    def models(self):
        return self._models

    def capabilities(self):
        return self._capabilities


class FakeFactory:
    @staticmethod
    def get_provider(provider: str, api_key: str):
        assert provider == "OpenAI"
        assert api_key == "secret"
        return FakeProvider()


def test_discovery_is_deterministic_and_policy_aware():
    discovery = ProviderCapabilityDiscovery(factory=FakeFactory)
    result = discovery.discover("OpenAI", "secret")

    assert result == (
        ProviderModelMetadata("openai", "model-a", ProviderCapabilities(streaming=True)),
        ProviderModelMetadata("openai", "model-b", ProviderCapabilities(streaming=True)),
    )


def test_capabilities_are_shared_from_governed_provider():
    capabilities = ProviderCapabilities(streaming=True, tools=False, vision=False)

    class Factory:
        @staticmethod
        def get_provider(provider: str, api_key: str):
            return FakeProvider(_models=("model-a",), _capabilities=capabilities)

    result = ProviderCapabilityDiscovery(factory=Factory).discover("anthropic", "secret")
    assert result[0].capabilities == capabilities
    assert result[0].capabilities.tools is False


def test_discovery_does_not_expose_credentials():
    discovery = ProviderCapabilityDiscovery(factory=FakeFactory)
    result = discovery.discover("OpenAI", "secret")
    assert "secret" not in repr(result)
    assert all(not hasattr(model, "api_key") for model in result)
