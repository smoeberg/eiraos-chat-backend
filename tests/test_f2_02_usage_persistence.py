from decimal import Decimal

from sqlalchemy import inspect

from eiraos.core.database import Base
from eiraos.domains.usage.models import ProviderUsageRecord


def test_provider_usage_record_contains_only_non_secret_accounting_fields():
    columns = set(ProviderUsageRecord.__table__.columns.keys())
    assert {
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
        "created_at",
    } <= columns
    assert "api_key" not in columns
    assert "secret" not in columns
    assert "authorization" not in columns
    assert "response_body" not in columns


def test_provider_usage_record_has_tenant_and_execution_indexes():
    indexes = {index.name for index in ProviderUsageRecord.__table__.indexes}
    assert "ix_provider_usage_records_user_id" in indexes
    assert "ix_provider_usage_records_organization_id" in indexes
    assert "ix_provider_usage_records_execution_id" in indexes
    assert "ix_provider_usage_records_request_id" in indexes


def test_cost_is_decimal_not_float():
    estimated = ProviderUsageRecord(
        request_id="req-1",
        execution_id="exec-1",
        user_id=1,
        organization_id=10,
        provider="openai",
        model="gpt-test",
        estimated_cost=Decimal("0.1234567890"),
        verification=False,
    )
    assert isinstance(estimated.estimated_cost, Decimal)
