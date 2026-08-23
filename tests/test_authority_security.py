"""Focused unit tests for the authority/security hardening layer.

These tests exercise pure logic and deliberately avoid requiring a live DB,
Redis, or external provider so they can run in CI without extra services.
"""
import os
import pytest
import jwt

from eiraos.api.v1.auth import (
    create_access_token,
    verify_password,
    get_password_hash,
    TOKEN_ISSUER,
    TOKEN_AUDIENCE,
)
from eiraos.core.secrets import SecretService
from eiraos.api.v1.auth import require_permission
from fastapi import HTTPException


# --- JWT claims completeness ------------------------------------------------
def test_access_token_contains_all_required_claims(monkeypatch):
    monkeypatch.setenv("EIRAOS_JWT_SECRET", "test-secret")
    from eiraos.core.config import settings
    if hasattr(settings, "SECRET_KEY"):
        settings.SECRET_KEY = "test-secret"

    token = create_access_token({
        "sub": "soeren@example.com",
        "user_id": 1,
        "role": "owner",
        "organization_id": 10,
    })
    import jwt
    payload = jwt.decode(token, "test-secret", algorithms=[settings.ALGORITHM],
                          issuer=TOKEN_ISSUER, audience=TOKEN_AUDIENCE)
    assert payload["iss"] == TOKEN_ISSUER
    assert payload["aud"] == TOKEN_AUDIENCE
    assert "iat" in payload
    assert "exp" in payload
    assert "jti" in payload           # unique token id, enables revocation
    assert "token_version" in payload  # used for revocation on logout
    assert payload["sub"] == "soeren@example.com"
    assert payload["organization_id"] == 10


def test_password_hash_roundtrip():
    password = "correct horse battery staple"
    hashed = get_password_hash(password)
    assert verify_password(password, hashed) is True
    assert verify_password("wrong", hashed) is False


# --- Idempotency digest stability ----------------------------------------
def test_idempotency_digest_is_stable():
    import hashlib
    d1 = hashlib.sha256(b'{"prompt":"hi"}').hexdigest()
    d2 = hashlib.sha256(b'{"prompt":"hi"}').hexdigest()
    d3 = hashlib.sha256(b'{"prompt":"bye"}').hexdigest()
    assert d1 == d2
    assert d1 != d3


# --- Secret resolution fails closed ---------------------------------------
def test_secret_service_fails_closed_when_unresolvable(monkeypatch):
    monkeypatch.delenv("EIRAOS_PROVIDER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(HTTPException) as exc:
        SecretService.resolve(1, "nonexistent-ref", None)
    assert exc.value.status_code == 500


def test_secret_service_returns_configured_key(monkeypatch):
    monkeypatch.setenv("EIRAOS_PROVIDER_MYKEY", "sk-abc123")
    assert SecretService.resolve(1, "mykey", None) == "sk-abc123"


def test_secret_service_prefers_reference_over_default(monkeypatch):
    monkeypatch.setenv("EIRAOS_PROVIDER_SPECIAL", "sk-special")
    monkeypatch.setenv("EIRAOS_PROVIDER_API_KEY", "sk-default")
    assert SecretService.resolve(1, "special", None) == "sk-special"


# --- RBAC permission mapping ----------------------------------------------
def test_owner_has_all_permissions():
    from eiraos.api.v1.auth import ROLE_PERMISSIONS
    assert "bot:delete" in ROLE_PERMISSIONS.get("owner", [])
    assert "organization:update" in ROLE_PERMISSIONS.get("owner", [])
    assert "conversation:delete" in ROLE_PERMISSIONS.get("owner", [])


# --- Sprint 2: visibility reconciliation ----------------------------------
def test_visibility_single_source_of_truth():
    """The legacy boolean and string visibility must never diverge."""
    from eiraos.domains.agents.models import Bot

    # is_public wins over a stale bot_visibility string
    a = Bot(is_public=True, bot_visibility="private")
    assert Bot.visibility(a) == "public"

    # bot_visibility string used when is_public is unset/falsy
    b = Bot(is_public=False, bot_visibility="knowledge")
    assert Bot.visibility(b) == "knowledge"

    # defaults to private
    c = Bot(is_public=False, bot_visibility=None)
    assert Bot.visibility(c) == "private"


def test_bot_create_rejects_contradictory_visibility():
    from pydantic import ValidationError
    from eiraos.api.v1.bots import BotCreateSchema

    # is_public=True but bot_visibility='private' is contradictory -> reject
    try:
        BotCreateSchema(title="x", is_public=True, bot_visibility="private")
        raised = False
    except ValidationError:
        raised = True
    assert raised

    # consistent public config is accepted
    ok = BotCreateSchema(title="x", is_public=True, bot_visibility="public")
    assert ok.is_public is True


# --- Sprint 2: SSE hardening constants -------------------------------------------   def test_sse_lifecycle_constants():
    """SSE heartbeat/timeout windows are the values we advertise."""
    from eiraos.api.v1 import chat
    assert chat.SSE_HEARTBEAT_SECONDS >= 10
    assert chat.SSE_CHUNK_TIMEOUT_SECONDS >= 20


# --- Sprint 20: token revocation is enforced at request time ------------

from eiraos.api.v1 import auth as auth_mod
from fastapi import HTTPException


class _FakeMembershipResult:
    def scalars(self):
        class S:
            def first(self):
                class M:
                    pass
                return M()
        return S()


class _FakeUserResult:
    def __init__(self, v):
        self._v = v

    def scalar_one_or_none(self):
        return _FakeUser(self._v)


class _FakeUser:
    def __init__(self, v):
        self.token_version = v


class _FakeDB:
    """Handles the two executes in get_current_active_organization."""
    def __init__(self, db_version):
        self._res = _FakeUserResult(db_version)

    async def execute(self, stmt):
        s = str(stmt)
        if "organ" in s:  # OrganizationMember query -> membership present
            return _FakeMembershipResult()
        return self._res  # User token_version query


def _active_org(current_user_version, db_version):
    import asyncio
    async def run():
        cu = {"organization_id": 1, "user_id": 1, "token_version": current_user_version}
        return await auth_mod.get_current_active_organization(current_user=cu, db=_FakeDB(db_version))
    return asyncio.run(run())


def test_revoked_token_version_rejected():
    # DB token_version bumped (logout/rotate) differs from token -> 401 revoked
    try:
        _active_org(1, 2)
        raised = False
    except HTTPException as e:
        raised = True
        assert e.status_code == 401
    assert raised


def test_matching_token_version_accepted():
    # token version matches DB -> not revoked, org id returned
    assert _active_org(3, 3) == 1
