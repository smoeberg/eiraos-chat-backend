import pytest
from fastapi import HTTPException

from eiraos.core.secrets import SecretService


def _resolve(**overrides):
    values = {
        "bot_owner_org_id": 10,
        "secret_reference": "ORG_A_KEY",
        "platform_api_key": None,
        "credential_scope": "organization",
        "caller_org_id": 10,
    }
    values.update(overrides)
    return SecretService.resolve(**values)


def test_organization_scope_requires_caller_org(monkeypatch):
    monkeypatch.setenv("EIRAOS_PROVIDER_ORG_A_KEY", "org-secret")
    with pytest.raises(HTTPException) as exc:
        _resolve(caller_org_id=None)
    assert exc.value.status_code == 403


def test_organization_scope_requires_bot_owner_org(monkeypatch):
    monkeypatch.setenv("EIRAOS_PROVIDER_ORG_A_KEY", "org-secret")
    with pytest.raises(HTTPException) as exc:
        _resolve(bot_owner_org_id=None)
    assert exc.value.status_code == 403


def test_different_org_cannot_resolve_organization_secret(monkeypatch):
    monkeypatch.setenv("EIRAOS_PROVIDER_ORG_A_KEY", "org-secret")
    with pytest.raises(HTTPException) as exc:
        _resolve(caller_org_id=11)
    assert exc.value.status_code == 403


def test_same_org_can_resolve_organization_secret(monkeypatch):
    monkeypatch.setenv("EIRAOS_PROVIDER_ORG_A_KEY", "org-secret")
    assert _resolve() == "org-secret"


def test_organization_scope_cannot_fallback_to_platform_credential(monkeypatch):
    monkeypatch.delenv("EIRAOS_PROVIDER_ORG_A_KEY", raising=False)
    monkeypatch.setenv("EIRAOS_PROVIDER_API_KEY", "platform-secret")
    with pytest.raises(HTTPException) as exc:
        _resolve()
    assert exc.value.status_code == 500


def test_platform_scope_can_use_platform_credential():
    assert _resolve(
        credential_scope="platform",
        secret_reference=None,
        platform_api_key="platform-secret",
    ) == "platform-secret"


def test_unknown_scope_is_rejected():
    with pytest.raises(HTTPException) as exc:
        _resolve(credential_scope="unknown")
    assert exc.value.status_code == 403


@pytest.mark.parametrize("reference", ["bad.ref", "bad ref", "bad/$", "", "a" * 101])
def test_invalid_secret_reference_is_rejected(reference):
    with pytest.raises(HTTPException) as exc:
        _resolve(secret_reference=reference)
    assert exc.value.status_code == 400
