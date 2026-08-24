"""Negative acceptance tests for F2-02 budget enforcement.

These tests define the required failure modes before the enforcement engine is
implemented. They intentionally fail while the capability is absent.
"""

import pytest


pytestmark = pytest.mark.f2_02_enforcement


class ProviderSpy:
    def __init__(self):
        self.calls = 0

    async def complete(self, *args, **kwargs):
        self.calls += 1
        return {"content": "unexpected provider execution"}


@pytest.mark.xfail(reason="F2-02 enforcement engine is not implemented yet", strict=True)
def test_user_quota_exhaustion_blocks_execution_before_provider_call():
    from eiraos.core.usage_budget import UsageBudgetGate

    provider = ProviderSpy()
    gate = UsageBudgetGate.for_test(user_remaining=0, organization_remaining=100)

    with pytest.raises(Exception):
        gate.reserve_or_raise(
            user_id=1,
            organization_id=10,
            estimated_cost=1,
            provider_call=provider,
        )

    assert provider.calls == 0


@pytest.mark.xfail(reason="F2-02 enforcement engine is not implemented yet", strict=True)
def test_organization_budget_exhaustion_blocks_execution_before_provider_call():
    from eiraos.core.usage_budget import UsageBudgetGate

    provider = ProviderSpy()
    gate = UsageBudgetGate.for_test(user_remaining=10, organization_remaining=0)

    with pytest.raises(Exception):
        gate.reserve_or_raise(
            user_id=1,
            organization_id=10,
            estimated_cost=1,
            provider_call=provider,
        )

    assert provider.calls == 0


@pytest.mark.xfail(reason="F2-02 enforcement engine is not implemented yet", strict=True)
def test_execution_cost_above_limit_is_denied():
    from eiraos.core.usage_budget import UsageBudgetGate

    gate = UsageBudgetGate.for_test(max_execution_cost=10)

    with pytest.raises(Exception):
        gate.reserve_or_raise(
            user_id=1,
            organization_id=10,
            estimated_cost=11,
        )


@pytest.mark.xfail(reason="F2-02 enforcement engine is not implemented yet", strict=True)
def test_verification_requires_budget_for_primary_and_verifier():
    from eiraos.core.usage_budget import UsageBudgetGate

    gate = UsageBudgetGate.for_test(organization_remaining=10)

    with pytest.raises(Exception):
        gate.reserve_or_raise(
            user_id=1,
            organization_id=10,
            estimated_cost=8,
            verification_estimated_cost=8,
        )


@pytest.mark.xfail(reason="F2-02 enforcement engine is not implemented yet", strict=True)
def test_budget_backend_unavailable_fails_closed():
    from eiraos.core.usage_budget import UsageBudgetGate

    gate = UsageBudgetGate.for_test(backend_available=False)

    with pytest.raises(Exception):
        gate.reserve_or_raise(
            user_id=1,
            organization_id=10,
            estimated_cost=1,
        )


@pytest.mark.xfail(reason="F2-02 enforcement engine is not implemented yet", strict=True)
def test_reservation_is_atomic_and_cannot_oversubscribe_budget():
    from eiraos.core.usage_budget import UsageBudgetGate

    gate = UsageBudgetGate.for_test(organization_remaining=10)

    first = gate.try_reserve(
        user_id=1,
        organization_id=10,
        estimated_cost=7,
    )
    second = gate.try_reserve(
        user_id=2,
        organization_id=10,
        estimated_cost=7,
    )

    assert [first, second].count(True) == 1


@pytest.mark.xfail(reason="F2-02 enforcement engine is not implemented yet", strict=True)
def test_rejected_reservation_never_initializes_provider_execution():
    from eiraos.core.usage_budget import UsageBudgetGate

    provider = ProviderSpy()
    gate = UsageBudgetGate.for_test(organization_remaining=0)

    assert gate.try_reserve(
        user_id=1,
        organization_id=10,
        estimated_cost=1,
    ) is False
    assert provider.calls == 0
