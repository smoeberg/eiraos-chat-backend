import dataclasses
from decimal import Decimal

import pytest

from eiraos.application.providers.base import ProviderCapabilities
from eiraos.application.providers.capability_discovery import (
    CATALOG_REVISION,
    MODEL_CAPABILITY_CATALOG,
    ProviderCapabilityDiscovery,
    ProviderModelMetadata,
    TokenPricing,
)


def test_catalog_covers_every_governed_provider_model():
    from eiraos.application.providers.policy import DEFAULT_PROVIDER_MODELS

    assert set(MODEL_CAPABILITY_CATALOG) == {
        (provider, model)
        for provider, models in DEFAULT_PROVIDER_MODELS.items()
        for model in models
    }


@pytest.mark.parametrize(
    "alias,normalized",
    [(" OpenAI ", "openai"), ("Claude", "anthropic"), ("Gemini", "google")],
)
def test_discovery_normalizes_provider_aliases_and_applies_policy(alias, normalized):
    result = ProviderCapabilityDiscovery().discover(alias, "secret")

    assert result
    assert all(item.provider == normalized for item in result)
    assert tuple(item.model for item in result) == tuple(dict.fromkeys(item.model for item in result))


def test_policy_filtered_models_are_not_discoverable(monkeypatch):
    monkeypatch.setenv("EIRAOS_ALLOWED_MODELS_OPENAI", "gpt-4o-mini")

    result = ProviderCapabilityDiscovery().discover("openai", "secret")

    assert tuple(item.model for item in result) == ("gpt-4o-mini",)


def test_effective_capabilities_are_intersection_with_adapter_implementation():
    result = ProviderCapabilityDiscovery().discover("openai", "secret")
    model = next(item for item in result if item.model == "gpt-4o")

    assert model.native_capabilities.vision
    assert model.native_capabilities.tools
    assert model.native_capabilities.structured_output
    assert model.capabilities == ProviderCapabilities(streaming=True)


def test_metadata_has_context_pricing_provenance_and_is_immutable():
    model = ProviderCapabilityDiscovery().discover("openai", "secret")[0]

    assert model.context_window_tokens > 0
    assert model.pricing.currency == "USD"
    assert model.pricing.unit_tokens == 1_000_000
    assert model.pricing.input_per_million >= Decimal("0")
    assert model.pricing.output_per_million >= Decimal("0")
    assert model.catalog_revision == CATALOG_REVISION
    with pytest.raises(dataclasses.FrozenInstanceError):
        model.context_window_tokens = 1


def test_invalid_pricing_and_context_metadata_fail_closed():
    with pytest.raises(ValueError, match="negative"):
        TokenPricing(Decimal("-1"), Decimal("1"))
    with pytest.raises(ValueError, match="denomination"):
        TokenPricing(Decimal("1"), Decimal("1"), currency="EUR")
    with pytest.raises(ValueError, match="Context window"):
        ProviderModelMetadata(
            provider="openai",
            model="model",
            capabilities=ProviderCapabilities(streaming=True),
            native_capabilities=ProviderCapabilities(streaming=True),
            context_window_tokens=0,
            pricing=TokenPricing(Decimal("1"), Decimal("1")),
        )


def test_unknown_catalog_model_fails_closed():
    class Provider:
        def models(self):
            return ("unknown",)

        def capabilities(self):
            return ProviderCapabilities(streaming=True, tools=True)

    class Factory:
        @staticmethod
        def get_provider(provider: str, api_key: str):
            return Provider()

    assert ProviderCapabilityDiscovery(factory=Factory).discover("openai", "secret") == ()


def test_discovery_does_not_expose_credentials_or_provider_instances():
    result = ProviderCapabilityDiscovery().discover("openai", "top-secret")

    assert "top-secret" not in repr(result)
    assert all(not hasattr(model, "api_key") for model in result)
    assert all(isinstance(model, ProviderModelMetadata) for model in result)
    assert all(isinstance(model.pricing, TokenPricing) for model in result)
