"""Negative acceptance tests for F2-02 budget enforcement."""

import pytest

pytestmark = pytest.mark.f2_02_enforcement


def test_user_quota_exhaustion_blocks_execution_before_provider_call():
    from eiraos.core.usage_budget import UsageBudgetGate

    gate = UsageBudgetGate.for_test(user_remaining=0, organization_remaining=100)
    with pytest.raises(Exception):
        gate.reserve_or_raise(user_id=1, organization_id=10, estimated_cost=1)


def test_organization_budget_exhaustion_blocks_execution_before_provider_call():
    from eiraos.core.usage_budget import UsageBudgetGate

    gate = UsageBudgetGate.for_test(user_remaining=10, organization_remaining=0)
    with pytest.raises(Exception):
        gate.reserve_or_raise(user_id=1, organization_id=10, estimated_cost=1)


def test_execution_cost_above_limit_is_denied():
    from eiraos.core.usage_budget import UsageBudgetGate

    gate = UsageBudgetGate.for_test(max_execution_cost=10)
    with pytest.raises(Exception):
        gate.reserve_or_raise(user_id=1, organization_id=10, estimated_cost=11)


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


def test_budget_backend_unavailable_fails_closed():
    from eiraos.core.usage_budget import UsageBudgetGate

    gate = UsageBudgetGate.for_test(backend_available=False)
    with pytest.raises(Exception):
        gate.reserve_or_raise(user_id=1, organization_id=10, estimated_cost=1)


def test_reservation_is_atomic_and_cannot_oversubscribe_budget():
    from eiraos.core.usage_budget import UsageBudgetGate

    gate = UsageBudgetGate.for_test(organization_remaining=10)
    first = gate.try_reserve(user_id=1, organization_id=10, estimated_cost=7)
    second = gate.try_reserve(user_id=2, organization_id=10, estimated_cost=7)
    assert [first, second].count(True) == 1
