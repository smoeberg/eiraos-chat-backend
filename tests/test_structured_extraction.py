import json

import pytest
from fastapi.testclient import TestClient
import httpx
from pydantic import ValidationError

from eiraos.application.providers.openai_adapter import OpenAIProviderAdapter
from eiraos.application.structured.schemas import ContentExtractionSchema
from eiraos.application.structured.service import StructuredExtractionService
from eiraos.api.v1.structured_tools import require_structured_tool_permission
from eiraos.api.v1.auth import get_current_active_organization, get_current_user
from eiraos.core.config import settings
from eiraos.core.exceptions import EiraOSException
from eiraos.main import app

SECRET = "TEST_PROVIDER_SECRET_7f3a9c"


def test_schema_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        ContentExtractionSchema.model_validate(
            {
                "title": "A",
                "summary": "B",
                "content_type": "article",
                "language": "da",
                "key_points": ["one"],
                "entities": [],
                "api_key": SECRET,
            }
        )


@pytest.mark.asyncio
async def test_structured_service_revalidates_provider_output_and_sanitizes_error():
    class FakeProvider:
        async def generate_structured_output(self, **kwargs):
            return {
                "title": "Test",
                "summary": "Summary",
                "content_type": "note",
                "language": "da",
                "key_points": ["one"],
                "entities": [],
                "unexpected": SECRET,
            }

    service = StructuredExtractionService(FakeProvider())
    with pytest.raises(EiraOSException) as exc:
        await service.extract("input", "test-model")
    assert exc.value.status_code == 502
    assert SECRET not in exc.value.detail


@pytest.mark.asyncio
async def test_openai_structured_request_uses_strict_json_schema(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": json.dumps({
                    "title": "Test",
                    "summary": "Summary",
                    "content_type": "note",
                    "language": "da",
                    "key_points": ["one"],
                    "entities": [],
                })}}]
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            captured.update(kwargs)
            # The credential is expected in the internal Authorization header.
            # It must never be serialized into the provider JSON payload.
            assert SECRET not in json.dumps(kwargs.get("json", {}))
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    adapter = OpenAIProviderAdapter(SECRET)
    result = await adapter.generate_structured_output(
        messages=[{"role": "user", "content": "hello"}],
        model="test-model",
        schema_name="content_extraction_v1",
        schema=ContentExtractionSchema.model_json_schema(),
    )

    assert result["title"] == "Test"
    assert captured["json"]["response_format"]["type"] == "json_schema"
    assert captured["json"]["response_format"]["json_schema"]["strict"] is True
    assert captured["json"]["temperature"] == 0


def test_extract_structure_requires_authentication():
    with TestClient(app) as client:
        response = client.post("/api/v1/tools/extract-structure", json={"text": "hello"})
    assert response.status_code == 401


def test_extract_structure_rejects_extra_request_fields():
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 7, "organization_id": 11}
    app.dependency_overrides[get_current_active_organization] = lambda: 11
    app.dependency_overrides[require_structured_tool_permission] = lambda: {"user_id": 7}
    old_key = settings.OPENAI_API_KEY
    settings.OPENAI_API_KEY = SECRET
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/tools/extract-structure",
                json={"text": "hello", "provider": "evil", "model": "privileged"},
            )
        assert response.status_code == 422
    finally:
        settings.OPENAI_API_KEY = old_key
        app.dependency_overrides.clear()


def test_extract_structure_returns_versioned_contract(monkeypatch):
    async def fake_structured_output(self, **kwargs):
        assert kwargs["model"] == settings.STRUCTURED_EXTRACTION_MODEL
        return {
            "title": "Test",
            "summary": "Summary",
            "content_type": "note",
            "language": "da",
            "key_points": ["one"],
            "entities": [],
        }

    monkeypatch.setattr(OpenAIProviderAdapter, "generate_structured_output", fake_structured_output)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 7, "organization_id": 11}
    app.dependency_overrides[get_current_active_organization] = lambda: 11
    app.dependency_overrides[require_structured_tool_permission] = lambda: {"user_id": 7}
    old_key = settings.OPENAI_API_KEY
    settings.OPENAI_API_KEY = SECRET
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/tools/extract-structure", json={"text": "hello"})
        assert response.status_code == 200
        body = response.json()
        assert body["schema_version"] == "1.0"
        assert body["data"]["content_type"] == "note"
        assert SECRET not in response.text
    finally:
        settings.OPENAI_API_KEY = old_key
        app.dependency_overrides.clear()
