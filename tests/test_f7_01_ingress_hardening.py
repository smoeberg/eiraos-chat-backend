import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from eiraos.core.config import Settings, settings
from eiraos.core.middleware import RequestBodyLoggingMiddleware, RequestTracingMiddleware


def app_with_body_boundary():
    app = FastAPI()
    app.add_middleware(RequestBodyLoggingMiddleware)

    @app.post("/echo")
    async def echo(request: Request):
        return {"size": len(await request.body()), "cached": len(request.state.cached_body)}

    return app


def test_declared_oversize_body_is_rejected_before_endpoint():
    client = TestClient(app_with_body_boundary())
    response = client.post(
        "/echo", content=b"x",
        headers={"content-length": str(settings.MAX_REQUEST_BODY_BYTES + 1)},
    )
    assert response.status_code == 413


def test_streamed_oversize_body_is_bounded_without_content_length():
    client = TestClient(app_with_body_boundary())

    def chunks():
        yield b"x" * settings.MAX_REQUEST_BODY_BYTES
        yield b"y"

    response = client.post("/echo", content=chunks(), headers={"transfer-encoding": "chunked"})
    assert response.status_code == 413


def test_valid_body_is_replayed_exactly_once():
    response = TestClient(app_with_body_boundary()).post("/echo", content=b"hello")
    assert response.status_code == 200
    assert response.json() == {"size": 5, "cached": 5}


def test_untrusted_request_id_is_replaced_not_reflected():
    app = FastAPI()
    app.add_middleware(RequestTracingMiddleware)

    @app.get("/")
    async def root(request: Request):
        return {"request_id": request.state.request_id}

    malicious = "bad\nlog-entry" + "x" * 200
    response = TestClient(app).get("/", headers={"X-Request-ID": malicious})
    assert response.status_code == 200
    assert malicious not in response.headers["X-Request-ID"]
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def production_settings(**overrides):
    values = dict(
        APP_ENV="production", SECRET_KEY="s" * 48,
        OPENAI_API_KEY="sk-real-production-key",
        REDIS_URL="redis://redis:6379/0",
        USER_TOKEN_BUDGET_LIMIT=1000,
        ORGANIZATION_TOKEN_BUDGET_LIMIT=10000,
        CORS_ORIGINS="https://app.example.com",
        TRUSTED_HOSTS="api.example.com",
    )
    values.update(overrides)
    return Settings(**values)


def test_production_ingress_configuration_is_fail_closed():
    assert production_settings().cors_origins == ("https://app.example.com",)
    with pytest.raises(ValueError, match="Redis"):
        production_settings(REDIS_URL="")
    with pytest.raises(ValueError, match="CORS"):
        production_settings(CORS_ORIGINS="http://localhost:3000")
    with pytest.raises(ValueError, match="trusted hosts"):
        production_settings(TRUSTED_HOSTS="*")
    with pytest.raises(ValueError, match="fallback"):
        production_settings(ALLOW_SYNC_INGEST_FALLBACK=True)
    with pytest.raises(ValueError, match="Redis URL"):
        production_settings(REDIS_URL="http://redis.example.com")
    with pytest.raises(ValueError, match="CORS"):
        production_settings(CORS_ORIGINS="https://user:pass@app.example.com/private")
    with pytest.raises(ValueError, match="trusted hosts"):
        production_settings(TRUSTED_HOSTS="*.example.com")


def test_unknown_environment_and_unbounded_body_limit_are_rejected():
    with pytest.raises(ValueError):
        Settings(APP_ENV="prod")
    with pytest.raises(ValueError):
        Settings(MAX_REQUEST_BODY_BYTES=100 * 1024 * 1024)
