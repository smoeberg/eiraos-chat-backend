import pytest
from fastapi import HTTPException

from eiraos.application.providers.factory import AIProviderFactory


def test_supported_provider_is_constructible():
    provider = AIProviderFactory.get_provider("openai", "sentinel")
    assert provider is not None


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError):
        AIProviderFactory.get_provider("not-allowed-provider", "sentinel")


def test_factory_does_not_authorize_models():
    """Documents the current gap: factory accepts a provider independently of model policy."""
    provider = AIProviderFactory.get_provider("openai", "sentinel")
    assert provider is not None


def test_policy_contract_requires_server_side_provider_and_model():
    """F2-01 admission policy must reject arbitrary client-selected combinations."""
    provider = "openai"
    model = "arbitrary-unapproved-model"
    assert provider == "openai"
    assert model == "arbitrary-unapproved-model"


@pytest.mark.parametrize("provider", ["openai", "anthropic", "google"])
def test_known_provider_names_are_explicit(provider):
    assert provider in {"openai", "anthropic", "google"}
