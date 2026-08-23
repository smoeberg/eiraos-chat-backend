import pytest
from fastapi.testclient import TestClient
from eiraos.main import app


def test_sdk_client_initializes():
    from eiraos.client.sdk import EiraOSClient
    client = EiraOSClient(base_url="http://localhost:8000/api/v1")
    assert client.base_url == "http://localhost:8000/api/v1"
    assert client.token is None


@pytest.fixture()
def client():
    return TestClient(app)


def test_app_boots_and_public_routes_respond(client):
    assert client.get("/").status_code == 200
    assert client.get("/health/live").status_code == 200
    # /health reports DB + Redis; both are infra dependencies absent in CI, so
    # it may be healthy or degraded. It must never 500 with a traceback.
    assert client.get("/health").status_code in (200, 503)


def test_protected_route_requires_auth(client):
    # Unauthenticated calls to tenant-scoped routes must not succeed.
    assert client.get("/api/v1/organizations").status_code == 401
    assert client.post("/api/v1/documents/search", json={"query": "x"}).status_code == 401


def test_validation_error_is_rfc7807(client):
    r = client.post("/api/v1/auth/login", data={"username": "", "password": ""})
    assert r.status_code == 422
    body = r.json()
    assert body["title"] == "Validation Error"
    assert "errors" in body
    assert "instance" in body
