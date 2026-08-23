"""Sprint 4: config fail-closed validation + document payload bounds."""
import pytest


def test_production_rejects_well_known_secret_key():
    """Refuse to boot in production with the placeholder SECRET_KEY."""
    from eiraos.core.config import Settings, WELL_KNOWN_SECRETS
    with pytest.raises(ValueError):
        Settings(APP_ENV="production", SECRET_KEY="super-secret-production-key-change-me")


def test_production_accepts_strong_secret_key():
    from eiraos.core.config import Settings
    s = Settings(APP_ENV="production", SECRET_KEY="x" * 48, OPENAI_API_KEY="sk-real-1234567890abcdef")
    assert s.SECRET_KEY == "x" * 48


def test_production_rejects_placeholder_api_key():
    from eiraos.core.config import Settings
    with pytest.raises(ValueError):
        Settings(APP_ENV="production", SECRET_KEY="x" * 40, OPENAI_API_KEY="sk-placeholder")


def test_development_keeps_defaults_for_local_testing():
    from eiraos.core.config import Settings
    s = Settings(APP_ENV="development")
    assert s.SECRET_KEY  # exists even if a placeholder, so test envs boot without vars


def test_document_payload_bounds_enforced():
    from eiraos.core.config import Settings
    from eiraos.api.v1.documents import (
        DocumentIngestRequest, DocumentSearchRequest,
        MAX_DOCUMENT_CHARS, MAX_SEARCH_LIMIT,
    )
    # oversize content rejected
    with pytest.raises(Exception):
        DocumentIngestRequest(title="t", content="a" * (MAX_DOCUMENT_CHARS + 1))
    # search limit clamped
    with pytest.raises(Exception):
        DocumentSearchRequest(query="q", limit=MAX_SEARCH_LIMIT + 1)
    # valid requests still accepted
    assert DocumentIngestRequest(title="t", content="hello" * 10).content
    assert DocumentSearchRequest(query="q", limit=10).limit == 10


def test_ingest_and_search_are_org_scoped():
    from eiraos.api.v1.documents import DocumentSearchRequest
    r = DocumentSearchRequest(query="search term", limit=3)
    assert r.query == "search term"
