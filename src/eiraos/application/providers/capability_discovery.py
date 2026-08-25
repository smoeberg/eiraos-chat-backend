"""F4-03 policy-aware, deterministic model capability discovery."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping

from eiraos.application.providers.base import ProviderCapabilities
from eiraos.application.providers.factory import AIProviderFactory
from eiraos.application.providers.policy import normalize_provider

CATALOG_REVISION = "2026-08-25"


@dataclass(frozen=True, slots=True)
class TokenPricing:
    """Standard text-token prices in USD per one million tokens."""

    input_per_million: Decimal
    output_per_million: Decimal
    currency: str = "USD"
    unit_tokens: int = 1_000_000

    def __post_init__(self) -> None:
        if self.input_per_million < 0 or self.output_per_million < 0:
            raise ValueError("Token prices cannot be negative")
        if self.currency != "USD" or self.unit_tokens != 1_000_000:
            raise ValueError("Unsupported token pricing denomination")


@dataclass(frozen=True, slots=True)
class ProviderModelMetadata:
    provider: str
    model: str
    capabilities: ProviderCapabilities
    native_capabilities: ProviderCapabilities
    context_window_tokens: int
    pricing: TokenPricing
    catalog_revision: str = CATALOG_REVISION

    def __post_init__(self) -> None:
        if not self.provider or not self.model or not self.catalog_revision:
            raise ValueError("Model metadata identity cannot be empty")
        if self.context_window_tokens <= 0:
            raise ValueError("Context window must be positive")


def _capabilities(*, vision: bool, tools: bool, structured_output: bool) -> ProviderCapabilities:
    return ProviderCapabilities(
        streaming=True,
        vision=vision,
        tools=tools,
        structured_output=structured_output,
    )


def _metadata(provider, model, context, input_price, output_price, native):
    return ProviderModelMetadata(
        provider=provider,
        model=model,
        capabilities=ProviderCapabilities(streaming=False),
        native_capabilities=native,
        context_window_tokens=context,
        pricing=TokenPricing(Decimal(input_price), Decimal(output_price)),
    )


_OPENAI_NATIVE = _capabilities(vision=True, tools=True, structured_output=True)
_ANTHROPIC_NATIVE = _capabilities(vision=True, tools=True, structured_output=False)
_GEMINI_NATIVE = _capabilities(vision=True, tools=True, structured_output=True)

MODEL_CAPABILITY_CATALOG: Mapping[tuple[str, str], ProviderModelMetadata] = MappingProxyType({
    ("openai", "gpt-4o"): _metadata("openai", "gpt-4o", 128_000, "2.50", "10.00", _OPENAI_NATIVE),
    ("openai", "gpt-4o-mini"): _metadata("openai", "gpt-4o-mini", 128_000, "0.15", "0.60", _OPENAI_NATIVE),
    ("openai", "gpt-4.1"): _metadata("openai", "gpt-4.1", 1_047_576, "2.00", "8.00", _OPENAI_NATIVE),
    ("openai", "gpt-4.1-mini"): _metadata("openai", "gpt-4.1-mini", 1_047_576, "0.40", "1.60", _OPENAI_NATIVE),
    ("anthropic", "claude-3-5-sonnet-20241022"): _metadata(
        "anthropic", "claude-3-5-sonnet-20241022", 200_000, "3.00", "15.00", _ANTHROPIC_NATIVE
    ),
    ("anthropic", "claude-3-5-haiku-20241022"): _metadata(
        "anthropic", "claude-3-5-haiku-20241022", 200_000, "0.80", "4.00", _ANTHROPIC_NATIVE
    ),
    ("google", "gemini-1.5-pro"): _metadata(
        "google", "gemini-1.5-pro", 2_000_000, "1.25", "5.00", _GEMINI_NATIVE
    ),
    ("google", "gemini-1.5-flash"): _metadata(
        "google", "gemini-1.5-flash", 1_000_000, "0.075", "0.30", _GEMINI_NATIVE
    ),
})


def model_metadata(provider: str, model: str) -> ProviderModelMetadata:
    normalized_provider = normalize_provider(provider)
    metadata = MODEL_CAPABILITY_CATALOG.get((normalized_provider, model))
    if metadata is None:
        raise ValueError("model capability metadata is unavailable")
    return metadata


def _implemented(native: ProviderCapabilities, adapter: ProviderCapabilities) -> ProviderCapabilities:
    """Expose only capabilities supported by both model and current adapter."""

    return ProviderCapabilities(**{
        field: bool(getattr(native, field) and getattr(adapter, field))
        for field in ProviderCapabilities.__dataclass_fields__
    })


class ProviderCapabilityDiscovery:
    """Discover governed model metadata without making an upstream request."""

    def __init__(self, factory=AIProviderFactory, catalog=MODEL_CAPABILITY_CATALOG):
        self._factory = factory
        self._catalog = catalog

    def discover(self, provider: str, api_key: str) -> tuple[ProviderModelMetadata, ...]:
        normalized_provider = normalize_provider(provider)
        governed = self._factory.get_provider(normalized_provider, api_key)
        adapter_capabilities = governed.capabilities()
        discovered = []
        for model in governed.models():
            metadata = self._catalog.get((normalized_provider, model))
            if metadata is None:
                continue
            discovered.append(replace(
                metadata,
                capabilities=_implemented(metadata.native_capabilities, adapter_capabilities),
            ))
        return tuple(discovered)