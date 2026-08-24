import pytest

from eiraos.domains.usage.cost_estimator import CostEstimator


def test_estimate_is_deterministic():
    estimator = CostEstimator(input_chars_per_token=4, output_tokens=100)
    assert estimator.estimate(prompt="abcd", verify=False).total_tokens == 101
    assert estimator.estimate(prompt="abcd", verify=False) == estimator.estimate(prompt="abcd", verify=False)


def test_verification_reserves_primary_and_verifier_budget():
    estimate = CostEstimator(output_tokens=100).estimate(prompt="abcd", verify=True)
    assert estimate.primary_tokens == 101
    assert estimate.verifier_tokens == 101
    assert estimate.total_tokens == 202


def test_empty_prompt_still_reserves_output_budget():
    estimate = CostEstimator(output_tokens=100).estimate(prompt="", verify=False)
    assert estimate.primary_tokens == 100


def test_invalid_configuration_is_rejected():
    with pytest.raises(ValueError):
        CostEstimator(input_chars_per_token=0)


def test_non_string_prompt_is_rejected():
    with pytest.raises(TypeError):
        CostEstimator().estimate(prompt=None, verify=False)
