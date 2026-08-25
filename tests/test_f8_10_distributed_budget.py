import pytest

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
    assert redis.calls[1][2] == 3


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
