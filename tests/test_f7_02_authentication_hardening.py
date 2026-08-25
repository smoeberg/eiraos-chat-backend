from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from eiraos.api.v1.auth import (
    TOKEN_AUDIENCE,
    TOKEN_ISSUER,
    UserRegister,
    get_current_user,
    verify_password,
)
from eiraos.core.config import Settings, settings
from eiraos.main import app
from fastapi.testclient import TestClient


def token(**overrides):
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "user@example.com", "user_id": 1, "organization_id": 2,
        "token_version": 1, "jti": "token-id", "iat": now,
        "exp": now + timedelta(minutes=5), "iss": TOKEN_ISSUER,
        "aud": TOKEN_AUDIENCE,
    }
    claims.update(overrides)
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def test_registration_enforces_bounded_password_policy():
    with pytest.raises(ValidationError):
        UserRegister(email="user@example.com", password="short")
    with pytest.raises(ValidationError):
        UserRegister(email="user@example.com", password="x" * 129)
    assert UserRegister(email="user@example.com", password="correct horse battery staple")


def test_public_registration_is_disabled_before_database_access(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_PUBLIC_REGISTER", False)
    response = TestClient(app).post("/api/v1/auth/register", json={
        "email": "new-user@example.com",
        "password": "correct horse battery staple",
    })
    assert response.status_code == 403
    assert response.json()["detail"] == "Public registration is disabled."


def test_public_registration_requires_explicit_opt_in():
    assert Settings().ALLOW_PUBLIC_REGISTER is False
    assert Settings(ALLOW_PUBLIC_REGISTER=True).ALLOW_PUBLIC_REGISTER is True


def test_password_verification_rejects_oversize_input_without_crashing():
    assert verify_password("x" * 1000, "$2b$12$invalidinvalidinvalidinvalidinvalidinvalidinvalidinvalidinv") is False


@pytest.mark.asyncio
@pytest.mark.parametrize("claim,value", [
    ("user_id", "1"), ("organization_id", True), ("token_version", 0), ("jti", ""),
])
async def test_jwt_identity_claims_have_strict_types(claim, value):
    with pytest.raises(HTTPException) as exc:
        await get_current_user(token=token(**{claim: value}))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_jwt_requires_jti_and_token_version():
    now = datetime.now(timezone.utc)
    incomplete = jwt.encode({
        "sub": "user@example.com", "user_id": 1, "organization_id": 2,
        "iat": now, "exp": now + timedelta(minutes=5),
        "iss": TOKEN_ISSUER, "aud": TOKEN_AUDIENCE,
    }, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    with pytest.raises(HTTPException) as exc:
        await get_current_user(token=incomplete)
    assert exc.value.status_code == 401


def test_jwt_algorithm_and_lifetime_are_bounded():
    with pytest.raises(ValueError, match="ALGORITHM"):
        Settings(ALGORITHM="none")
    with pytest.raises(ValueError):
        Settings(ACCESS_TOKEN_EXPIRE_MINUTES=0)
    with pytest.raises(ValueError):
        Settings(ACCESS_TOKEN_EXPIRE_MINUTES=1441)
