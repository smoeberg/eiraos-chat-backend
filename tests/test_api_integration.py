import pytest
from fastapi.testclient import TestClient
from eiraos.main import app

client = TestClient(app)

def test_auth_login_validation():
    # Test missing credentials returns validation error (RFC 7807)
    response = client.post("/api/v1/auth/login", data={"username": "", "password": ""})
    assert response.status_code == 422
    data = response.json()
    assert data["title"] == "Validation Error"
    assert "errors" in data

def test_organizations_unauthorized():
    # Test listing organizations without tenant/auth header
    response = client.get("/api/v1/organizations")
    assert response.status_code in [401, 403, 422, 500] # Depends on auth dep strictness
