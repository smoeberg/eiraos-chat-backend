"""F4-03 capability discovery and model metadata.

Discovery is read-only and policy-aware: it exposes only models returned by the
provider's governed catalog and only capability flags advertised by the current
adapter. No credentials or provider instances are exposed by this contract.
"""
from __future__ import annotations

from dataclasses import dataclass

from eiraos.application.providers.base import ProviderCapabilities
from eiraos.application.providers.factory import AIProviderFactory


@dataclass(frozen=True, slots=True)
class ProviderModelMetadata:
    provider: str
    model: str
    capabilities: ProviderCapabilities


class ProviderCapabilityDiscovery:
    """Discover governed provider models without executing upstream requests."""

    def __init__(self, factory=AIProviderFactory):
        self._factory = factory

    def discover(self, provider: str, api_key: str) -> tuple[ProviderModelMetadata, ...]:
        governed = self._factory.get_provider(provider, api_key)
        normalized_provider = provider.lower()
        capabilities = governed.capabilities()
        return tuple(
            ProviderModelMetadata(
                provider=normalized_provider,
                model=model,
                capabilities=capabilities,
            )
            for model in governed.models()
        )
