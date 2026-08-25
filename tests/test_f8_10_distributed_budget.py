import pytest
import httpx

from eiraos.domains.usage.cost_estimator import CostEstimator
from eiraos.domains.usage.execution_budget import ExecutionBudget
from eiraos.domains.usage.redis_reservation import RedisUsageReservation


class FakeRedis:
    def __init__(self, result=1):
        self.result = result
        self.calls = []

    async def eval(self, *args):
        self.calls.append(args)
        return self.result


def production_settings_values():
    return dict(
        APP_ENV="production", SECRET_KEY="s" * 48,
        REDIS_URL="redis://redis:6379/0",
        CORS_ORIGINS="https://app.example.com", TRUSTED_HOSTS="api.example.com",
        USER_TOKEN_BUDGET_LIMIT=1000, ORGANIZATION_TOKEN_BUDGET_LIMIT=10000,
    )


@pytest.mark.asyncio
async def test_user_and_organization_tokens_are_reserved_atomically():
    redis = FakeRedis()
    reservation = await ExecutionBudget(
        CostEstimator(output_tokens=10), RedisUsageReservation(redis)
    ).reserve(
        reservation_id="execution-1", user_id=7, organization_id=11,
        prompt="hello", verify=True, user_limit=100, organization_limit=200,
    )

    assert reservation.total_reserved_tokens == 24
    call = redis.calls[0]
    assert call[1] == 3
    assert call[2].startswith("budget:{11}:organization:tokens:reservation:")
    assert call[3] == "budget:{11}:user:7:tokens"
    assert call[4] == "budget:{11}:organization:tokens"
    assert call[5] == 24


@pytest.mark.asyncio
async def test_execution_replay_is_reported_without_second_reservation():
    reservation = await ExecutionBudget(
        CostEstimator(output_tokens=1), RedisUsageReservation(FakeRedis(result=2))
    ).reserve(
        reservation_id="same-execution", user_id=1, organization_id=2,
        prompt="x", verify=False, user_limit=10, organization_limit=10,
    )
    assert reservation.tenant.replayed is True


@pytest.mark.asyncio
async def test_release_decrements_both_scopes_and_deletes_identity_marker():
    redis = FakeRedis()
    reservations = RedisUsageReservation(redis)
    reservation = await ExecutionBudget(
        CostEstimator(), reservations,
    ).reserve(
        reservation_id="execution-3", user_id=7, organization_id=11,
        prompt="hello", verify=False, user_limit=5000, organization_limit=10000,
    )
    await reservations.release_tenant(reservation.tenant)
    assert len(redis.calls) == 2
    assert redis.calls[1][1] == 3


@pytest.mark.asyncio
async def test_provider_usage_settlement_updates_both_scopes_once():
    redis = FakeRedis()
    budget = ExecutionBudget(CostEstimator(output_tokens=10), RedisUsageReservation(redis))
    reservation = await budget.reserve(
        reservation_id="execution-4", user_id=7, organization_id=11,
        prompt="hello", verify=False, user_limit=5000, organization_limit=10000,
    )
    assert await budget.settle(reservation, actual_tokens=17) is True
    call = redis.calls[1]
    assert call[1] == 4
    assert call[3].endswith(":settled")
    assert call[7] == 17


def test_provider_usage_is_strictly_typed_and_priced_as_reported():
    from eiraos.application.cost_accounting import ExecutionCostAccountant
    from eiraos.application.providers.openai_adapter import _usage

    usage = _usage(
        {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
        "prompt_tokens", "completion_tokens", total_key="total_tokens",
    )
    assert usage is not None and usage.total_tokens == 17
    assert _usage({"prompt_tokens": True, "completion_tokens": 5},
                  "prompt_tokens", "completion_tokens") is None
    assert _usage(
        {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 99},
        "prompt_tokens", "completion_tokens", total_key="total_tokens",
    ) is None
    entry = ExecutionCostAccountant().account_reported(
        provider="openai", model="gpt-4o", operation="primary",
        input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
    )
    assert entry.usage_source == "provider_reported"
    assert entry.total_tokens == 17


def test_non_streaming_runtime_reconciles_provider_reported_usage():
    from pathlib import Path
    source = Path("src/eiraos/api/v1/chat.py").read_text()
    assert 'getattr(provider, "complete_with_usage", None)' in source
    assert "settle_primary_usage(completion.usage)" in source
    assert 'getattr(provider, "stream_with_usage", None)' in source
    assert "await settle_primary_usage(stream_usage)" in source


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("adapter_path", "payload", "expected"),
    [
        (
            "openai", {"choices": [{"message": {"content": "ok"}}],
                       "usage": {"prompt_tokens": 8, "completion_tokens": 3,
                                 "total_tokens": 11}}, 11,
        ),
        (
            "anthropic", {"content": [{"text": "ok"}],
                          "usage": {"input_tokens": 8, "output_tokens": 3}}, 11,
        ),
        (
            "gemini", {"candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                       "usageMetadata": {"promptTokenCount": 8,
                                         "candidatesTokenCount": 2,
                                         "thoughtsTokenCount": 1,
                                         "totalTokenCount": 11}}, 11,
        ),
    ],
)
async def test_adapters_preserve_valid_provider_usage(adapter_path, payload, expected):
    from eiraos.application.providers.anthropic_adapter import AnthropicProviderAdapter
    from eiraos.application.providers.gemini_adapter import GeminiProviderAdapter
    from eiraos.application.providers.openai_adapter import OpenAIProviderAdapter

    adapter_class = {
        "openai": OpenAIProviderAdapter,
        "anthropic": AnthropicProviderAdapter,
        "gemini": GeminiProviderAdapter,
    }[adapter_path]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    result = await adapter_class("key", transport=transport).complete_with_usage(
        messages=[{"role": "user", "content": "hi"}], model="model",
    )
    assert result.text == "ok"
    assert result.usage is not None and result.usage.total_tokens == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("adapter_path", "body"),
    [
        ("openai", 'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
                   'data: {"choices":[],"usage":{"prompt_tokens":8,'
                   '"completion_tokens":3,"total_tokens":11}}\n\n'),
        ("anthropic", 'data: {"type":"message_start","message":{"usage":'
                      '{"input_tokens":8}}}\n\n'
                      'data: {"type":"content_block_delta","delta":'
                      '{"type":"text_delta","text":"ok"}}\n\n'
                      'data: {"type":"message_delta","usage":'
                      '{"output_tokens":3}}\n\n'),
        ("gemini", 'data: {"candidates":[{"content":{"parts":[{"text":"ok"}]}}],'
                   '"usageMetadata":{"promptTokenCount":8,"totalTokenCount":11}}\n\n'),
    ],
)
async def test_stream_adapters_emit_text_and_terminal_usage(adapter_path, body):
    from eiraos.application.providers.anthropic_adapter import AnthropicProviderAdapter
    from eiraos.application.providers.gemini_adapter import GeminiProviderAdapter
    from eiraos.application.providers.openai_adapter import OpenAIProviderAdapter

    adapter_class = {
        "openai": OpenAIProviderAdapter,
        "anthropic": AnthropicProviderAdapter,
        "gemini": GeminiProviderAdapter,
    }[adapter_path]
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    )
    events = [event async for event in adapter_class(
        "key", transport=transport,
    ).stream_with_usage(messages=[{"role": "user", "content": "hi"}], model="model")]
    assert [event.text for event in events if event.text is not None] == ["ok"]
    usage = [event.usage for event in events if event.usage is not None]
    assert len(usage) == 1 and usage[0].total_tokens == 11


def test_production_requires_explicit_user_and_organization_token_limits():
    from eiraos.core.config import Settings

    values = production_settings_values()
    assert Settings(**values).USER_TOKEN_BUDGET_LIMIT == 1000
    for missing in ("USER_TOKEN_BUDGET_LIMIT", "ORGANIZATION_TOKEN_BUDGET_LIMIT"):
        incomplete = values.copy()
        incomplete.pop(missing)
        with pytest.raises(ValueError, match="token budget limit"):
            Settings(**incomplete)


def test_chat_runtime_uses_distributed_budget_outside_development():
    from pathlib import Path
    source = Path("src/eiraos/api/v1/chat.py").read_text()
    assert 'if settings.APP_ENV != "development"' in source
    assert "DistributedExecutionBudget" in source
    assert "RedisUsageReservation" in source
