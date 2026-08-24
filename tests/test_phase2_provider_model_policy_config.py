import pytest
from fastapi import HTTPException

from eiraos.application.providers.policy import authorize_provider_model


def test_provider_model_allowlist_can_be_explicitly_configured(monkeypatch):
    monkeypatch.setenv("EIRAOS_ALLOWED_MODELS_OPENAI", "internal-test-model,gpt-4o")
    assert authorize_provider_model("openai", "internal-test-model") == ("openai", "internal-test-model")
    with pytest.raises(HTTPException):
        authorize_provider_model("openai", "gpt-4.1")
