import pytest

from eiraos.domains.usage.cost_estimator import CostEstimator
from eiraos.domains.usage.execution_budget import ExecutionBudget
from eiraos.domains.usage.redis_reservation import RedisUsageReservation, BudgetReservationDenied


class FakeRedis:
    def __init__(self):
        self.values = {}
    async def eval(self, script, n, key, amount, limit, ttl):
        current = self.values.get(key, 0)
        if current + amount > limit:
            return 0
        self.values[key] = current + amount
        return 1
    async def decrby(self, key, amount):
        self.values[key] = self.values.get(key, 0) - amount


@pytest.mark.asyncio
async def test_primary_and_verifier_are_reserved_before_execution():
    redis = FakeRedis()
    budget = ExecutionBudget(CostEstimator(output_tokens=10), RedisUsageReservation(redis))
    reservation = await budget.reserve(user_id=1, organization_id=2, prompt="abcd", verify=True, user_limit=100, organization_limit=100)
    assert reservation.estimate.total_tokens == 22
    assert redis.values["user:1:budget"] == 11
    assert redis.values["user:1:verification"] == 11


@pytest.mark.asyncio
async def test_verifier_reservation_failure_rolls_back_primary():
    redis = FakeRedis()
    budget = ExecutionBudget(CostEstimator(output_tokens=10), RedisUsageReservation(redis))
    with pytest.raises(RuntimeError):
        await budget.reserve(user_id=1, organization_id=2, prompt="abcd", verify=True, user_limit=15, organization_limit=100)
    assert redis.values == {}


@pytest.mark.asyncio
async def test_release_returns_reservation():
    redis = FakeRedis()
    budget = ExecutionBudget(CostEstimator(output_tokens=10), RedisUsageReservation(redis))
    reservation = await budget.reserve(user_id=1, organization_id=2, prompt="abcd", verify=False, user_limit=100, organization_limit=100)
    await budget.release(reservation)
    assert redis.values["user:1:budget"] == 0
