import pytest

from eiraos.application.usage_execution import ProviderExecutionBudget
from eiraos.core.usage_budget import BudgetExceeded, BudgetUnavailable, UsageBudgetGate
from eiraos.domains.usage.cost_estimator import CostEstimator


def test_reserves_before_provider_execution():
    boundary = ProviderExecutionBudget(
        estimator=CostEstimator(output_tokens=10),
        gate_factory=lambda: UsageBudgetGate.for_test(user_remaining=1000, organization_remaining=1000),
    )

    result = boundary.reserve(
        user_id=1,
        organization_id=2,
        prompt="hello",
        verify=True,
    )

    assert result.estimate.primary_tokens == 12
    assert result.estimate.verifier_tokens == 12
    assert result.reservation.total_reserved_cost == 24


def test_denies_execution_when_budget_is_exceeded():
    boundary = ProviderExecutionBudget(
        estimator=CostEstimator(output_tokens=10),
        gate_factory=lambda: UsageBudgetGate.for_test(user_remaining=10),
    )

    with pytest.raises(BudgetExceeded):
        boundary.reserve(user_id=1, organization_id=2, prompt="hello", verify=False)


def test_backend_unavailable_fails_closed():
    boundary = ProviderExecutionBudget(
        estimator=CostEstimator(output_tokens=10),
        gate_factory=lambda: UsageBudgetGate.for_test(backend_available=False),
    )

    with pytest.raises(BudgetUnavailable):
        boundary.reserve(user_id=1, organization_id=2, prompt="hello", verify=False)
