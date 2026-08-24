import pytest

from eiraos.domains.usage.redis_reservation import (
    BudgetBackendUnavailable,
    BudgetReservationDenied,
    RedisUsageReservation,
)


class FakeRedis:
    def __init__(self, value=0, fail=False):
        self.value = value
        self.fail = fail
        self.calls = []

    async def eval(self, script, numkeys, key, amount, limit, ttl):
        self.calls.append((key, amount, limit, ttl))
        if self.fail:
            raise RuntimeError("redis down")
        if self.value + amount > limit:
            return 0
        self.value += amount
        return 1

    async def decrby(self, key, amount):
        if self.fail:
            raise RuntimeError("redis down")
        self.value -= amount


@pytest.mark.asyncio
async def test_reservation_is_atomic_and_records_expected_key():
    redis = FakeRedis()
    reservation = RedisUsageReservation(redis)
    result = await reservation.reserve("org:10:cost", 7, 10, 3600)
    assert result.amount == 7
    assert redis.value == 7
    assert redis.calls == [("org:10:cost", 7, 10, 3600)]


@pytest.mark.asyncio
async def test_reservation_denied_without_mutating_counter():
    redis = FakeRedis(value=8)
    reservation = RedisUsageReservation(redis)
    with pytest.raises(BudgetReservationDenied):
        await reservation.reserve("org:10:cost", 3, 10, 3600)
    assert redis.value == 8


@pytest.mark.asyncio
async def test_backend_failure_fails_closed():
    redis = FakeRedis(fail=True)
    reservation = RedisUsageReservation(redis)
    with pytest.raises(BudgetBackendUnavailable):
        await reservation.reserve("org:10:cost", 1, 10, 3600)


@pytest.mark.asyncio
async def test_release_returns_reserved_amount():
    redis = FakeRedis(value=7)
    reservation = RedisUsageReservation(redis)
    result = await reservation.reserve("org:10:cost", 3, 10, 3600)
    await reservation.release(result)
    assert redis.value == 7


@pytest.mark.asyncio
async def test_release_backend_failure_fails_closed():
    redis = FakeRedis(value=3, fail=True)
    reservation = RedisUsageReservation(redis)
    with pytest.raises(BudgetBackendUnavailable):
        await reservation.release(type("R", (), {"key": "org:10:cost", "amount": 1})())
