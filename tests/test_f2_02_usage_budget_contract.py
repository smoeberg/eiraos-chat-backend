"""Contract tests for F2-02 usage and budget enforcement.

These tests intentionally describe the required enforcement boundary before the
quota/budget implementation exists.
"""

from pathlib import Path


CONTRACT_PATH = Path("docs/architecture/F2-02-00-usage-budget-contract.md")


def _contract_text() -> str:
    return CONTRACT_PATH.read_text(encoding="utf-8")


def test_usage_contract_defines_required_identity_and_usage_fields():
    text = _contract_text()
    for field in (
        "request_id",
        "execution_id",
        "user_id",
        "organization_id",
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "estimated_cost",
        "actual_cost",
        "verification",
        "timestamp",
    ):
        assert f"`{field}`" in text


def test_usage_contract_separates_rate_limit_quota_and_budget():
    text = _contract_text()
    assert "Rate limiting, quota enforcement, and cost budgeting are separate controls." in text


def test_budget_is_checked_before_provider_execution():
    text = _contract_text()
    assert "Budget checks occur before provider execution." in text
    assert "reserve user quota" in text
    assert "reserve organization budget" in text


def test_verification_is_metered_and_cannot_bypass_budget():
    text = _contract_text()
    assert "Verification executions consume the same budget as primary executions." in text
    assert "cannot create an unmetered secondary execution" in text


def test_contract_requires_atomic_reservation():
    text = _contract_text()
    assert "All reservations must be atomic." in text
    assert "failed reservation must prevent provider execution" in text


def test_contract_defines_user_organization_and_execution_scopes():
    text = _contract_text()
    for scope in ("### User", "### Organization", "### Execution"):
        assert scope in text


def test_contract_assigns_hot_path_and_durable_storage_responsibilities():
    text = _contract_text()
    assert "Redis: atomic counters/reservations and hot-path enforcement." in text
    assert "PostgreSQL: durable usage/audit history and reporting." in text


def test_contract_fails_closed_when_budget_state_is_unknown():
    text = _contract_text()
    assert "Unknown or unavailable budget state fails closed." in text
    assert "Deny execution when:" in text


def test_usage_contract_never_records_secrets():
    text = _contract_text()
    assert "Usage records must never contain secrets or authorization headers." in text
