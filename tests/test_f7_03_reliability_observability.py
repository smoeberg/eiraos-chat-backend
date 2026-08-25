import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.trustedhost import TrustedHostMiddleware

from eiraos.core.config import settings
from eiraos.core.middleware import (
    RequestBodyLoggingMiddleware,
    RequestTracingMiddleware,
    SecurityHeadersMiddleware,
)


def test_early_ingress_rejections_are_correlated_and_hardened():
    from eiraos.main import app

    response = TestClient(app).post(
        "/api/v1/auth/register", content=b"x",
        headers={"content-length": str(settings.MAX_REQUEST_BODY_BYTES + 1)},
    )
    assert response.status_code == 413
    assert response.headers["x-request-id"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_middleware_order_keeps_tracing_and_headers_outside_ingress_boundaries():
    from eiraos.main import app

    order = [item.cls for item in app.user_middleware]
    assert order.index(RequestTracingMiddleware) < order.index(SecurityHeadersMiddleware)
    assert order.index(SecurityHeadersMiddleware) < order.index(TrustedHostMiddleware)
    assert order.index(TrustedHostMiddleware) < order.index(RequestBodyLoggingMiddleware)


def test_request_completion_emits_bounded_operational_fields(monkeypatch):
    from eiraos.core import middleware

    events = []
    monkeypatch.setattr(middleware.logger, "info", lambda event, **fields: events.append((event, fields)))
    app = FastAPI()
    app.add_middleware(RequestTracingMiddleware)

    @app.get("/")
    async def ok():
        return {"ok": True}

    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert events[0][0] == "request_completed"
    assert events[0][1]["status_code"] == 200
    assert events[0][1]["duration_ms"] >= 0
    assert "request" not in events[0][1]


@pytest.mark.asyncio
async def test_lifespan_disposes_database_engine(monkeypatch):
    from eiraos import main

    disposed = False

    class FakeEngine:
        async def dispose(self):
            nonlocal disposed
            disposed = True

    monkeypatch.setattr(main, "engine", FakeEngine())
    async with main.lifespan(main.app):
        assert disposed is False
    assert disposed is True


@pytest.mark.asyncio
async def test_failed_redis_readiness_probe_closes_client(monkeypatch):
    from eiraos import main

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, _query):
            return None

    class Redis:
        closed = False

        async def ping(self):
            raise ConnectionError("credential-bearing message must not escape")

        async def aclose(self):
            self.closed = True

    redis = Redis()
    monkeypatch.setattr(main, "AsyncSessionLocal", Session)
    monkeypatch.setattr(main.settings, "REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setattr(main.aioredis, "from_url", lambda *_args, **_kwargs: redis)
    response = await main.health_ready()
    assert response.status_code == 503
    assert redis.closed is True
    assert b"credential-bearing" not in response.body


def test_production_disables_interactive_api_documentation():
    source = __import__("inspect").getsource(__import__("eiraos.main", fromlist=["app"]))
    assert 'docs_url=None if settings.APP_ENV == "production"' in source
    assert 'redoc_url=None if settings.APP_ENV == "production"' in source
