from unittest.mock import AsyncMock, Mock

import pytest

from eiraos.application.chat_execution import ChatExecutionBoundary, IdempotencyReservation


def _boundary(events, *, authorize=None, idem=None, budget=None, provider=None, persist=None):
    async def _authorize():
        events.append("authorize")
        if authorize:
            return await authorize()
        return "scope"

    async def _idem():
        events.append("idempotency")
        if idem:
            return await idem()
        return IdempotencyReservation("key", "lease")

    def _budget(scope):
        events.append("budget")
        if budget:
            return budget(scope)

    async def _provider(scope):
        events.append("provider")
        if provider:
            return await provider(scope)
        return "provider-context"

    async def _persist(scope):
        events.append("persistence")
        if persist:
            await persist(scope)

    return ChatExecutionBoundary(
        authorize=_authorize,
        reserve_idempotency=_idem,
        reserve_budget=_budget,
        prepare_provider=_provider,
        persist_request=_persist,
    )


@pytest.mark.asyncio
async def test_contract_orders_all_preflight_operations():
    events = []
    result = await _boundary(events).prepare()
    assert events == ["authorize", "idempotency", "budget", "persistence", "provider"]
    assert result.authorized == "scope"
    assert result.provider_context == "provider-context"
    assert not result.is_replay


@pytest.mark.asyncio
async def test_replay_short_circuits_before_budget_provider_and_writes():
    events = []
    replay = {"role": "assistant", "content": "cached"}
    idem = AsyncMock(return_value=IdempotencyReservation("key", None, replay))
    result = await _boundary(events, idem=idem).prepare()
    assert events == ["authorize", "idempotency"]
    assert result.is_replay
    assert result.cached_response == replay


@pytest.mark.asyncio
async def test_budget_boundary_accepts_async_distributed_reservation():
    events = []

    async def budget(scope):
        events.append("async-budget")

    result = await _boundary(events, budget=budget).prepare()
    assert result.provider_context == "provider-context"
    assert events == [
        "authorize", "idempotency", "budget", "async-budget", "persistence", "provider"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_step", ["authorize", "idempotency", "budget", "provider", "persistence"])
async def test_failure_stops_all_later_operations(failure_step):
    events = []
    error = RuntimeError(failure_step)
    authorize = AsyncMock(side_effect=error) if failure_step == "authorize" else None
    idem = AsyncMock(side_effect=error) if failure_step == "idempotency" else None
    budget = Mock(side_effect=error) if failure_step == "budget" else None
    provider = AsyncMock(side_effect=error) if failure_step == "provider" else None
    persist = AsyncMock(side_effect=error) if failure_step == "persistence" else None
    with pytest.raises(RuntimeError, match=failure_step):
        await _boundary(events, authorize=authorize, idem=idem, budget=budget, provider=provider, persist=persist).prepare()
    order = ["authorize", "idempotency", "budget", "persistence", "provider"]
    assert events == order[: order.index(failure_step) + 1]
