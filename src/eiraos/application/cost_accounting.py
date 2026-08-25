"""F4-05 deterministic, execution-linked provider cost accounting."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping, Sequence

from eiraos.application.providers.base import ChatMessage
from eiraos.application.providers.capability_discovery import (
    CATALOG_REVISION,
    MODEL_CAPABILITY_CATALOG,
)
from eiraos.application.providers.policy import normalize_provider

_COST_QUANTUM = Decimal("0.0000000001")


class CostAccountingUnavailable(RuntimeError):
    """Raised when an execution cannot be priced from the governed catalog."""


@dataclass(frozen=True, slots=True)
class ExecutionCost:
    provider: str
    model: str
    operation: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost: Decimal
    usage_source: str
    pricing_revision: str

    def __post_init__(self) -> None:
        if not self.provider or not self.model or not self.pricing_revision:
            raise ValueError("accounting identity cannot be empty")
        if self.operation not in {"primary", "verification"}:
            raise ValueError("unsupported provider accounting operation")
        if min(self.input_tokens, self.output_tokens, self.total_tokens) < 0:
            raise ValueError("token counts cannot be negative")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total tokens must equal input plus output")
        if self.cost < 0 or self.usage_source not in {"estimated", "provider_reported"}:
            raise ValueError("invalid execution cost metadata")


class ExecutionCostAccountant:
    """Estimate final text usage when the canonical provider lacks usage output."""

    def __init__(self, *, chars_per_token: int = 4, catalog: Mapping = MODEL_CAPABILITY_CATALOG):
        if chars_per_token <= 0:
            raise ValueError("chars_per_token must be positive")
        self._chars_per_token = chars_per_token
        self._catalog = catalog

    def account(
        self,
        *,
        provider: str,
        model: str,
        operation: str,
        messages: Sequence[ChatMessage],
        output: str,
        system_prompt: str | None = None,
    ) -> ExecutionCost:
        try:
            normalized = normalize_provider(provider)
        except Exception as exc:
            raise CostAccountingUnavailable("provider pricing metadata is unavailable") from exc
        metadata = self._catalog.get((normalized, model))
        if metadata is None:
            raise CostAccountingUnavailable("model pricing metadata is unavailable")
        input_chars = len(system_prompt or "") + sum(
            len(str(message.get("content") or "")) for message in messages
        )
        input_tokens = self._tokens(input_chars)
        output_tokens = self._tokens(len(output))
        pricing = metadata.pricing
        cost = (
            Decimal(input_tokens) * pricing.input_per_million
            + Decimal(output_tokens) * pricing.output_per_million
        ) / Decimal(pricing.unit_tokens)
        return ExecutionCost(
            provider=normalized,
            model=model,
            operation=operation,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost=cost.quantize(_COST_QUANTUM, rounding=ROUND_HALF_UP),
            usage_source="estimated",
            pricing_revision=CATALOG_REVISION,
        )

    def account_reported(self, *, provider: str, model: str, operation: str,
                         input_tokens: int, output_tokens: int) -> ExecutionCost:
        try:
            normalized = normalize_provider(provider)
        except Exception as exc:
            raise CostAccountingUnavailable("provider pricing metadata is unavailable") from exc
        metadata = self._catalog.get((normalized, model))
        if metadata is None:
            raise CostAccountingUnavailable("model pricing metadata is unavailable")
        pricing = metadata.pricing
        cost = (
            Decimal(input_tokens) * pricing.input_per_million
            + Decimal(output_tokens) * pricing.output_per_million
        ) / Decimal(pricing.unit_tokens)
        return ExecutionCost(
            provider=normalized, model=model, operation=operation,
            input_tokens=input_tokens, output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost=cost.quantize(_COST_QUANTUM, rounding=ROUND_HALF_UP),
            usage_source="provider_reported", pricing_revision=CATALOG_REVISION,
        )

    def _tokens(self, characters: int) -> int:
        return (characters + self._chars_per_token - 1) // self._chars_per_token
