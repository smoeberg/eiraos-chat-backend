import pytest
from fastapi.testclient import TestClient
from eiraos.main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    # In CI/test environment without local postgres/redis running, health returns 503 degraded or 200 healthy
    assert response.status_code in [200, 503]
    data = response.json()
    assert "status" in data
    assert "database" in data
    assert "redis" in data
