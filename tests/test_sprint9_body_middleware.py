import asyncio

from starlette.requests import Request
from starlette.datastructures import State

from eiraos.core import idempotency
from eiraos.main import app


def _make_request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/chat/completions",
        "headers": [(b"content-type", b"application/json")],
        "query_string": b"",
        "state": {},
        "app": None,
    }
    request = Request(scope)
    return request


def test_idempotency_digest_fails_closed_without_cached_body():
    """_body_digest must not crash when no middleware captured the body."""
    req = _make_request()
    digest = idempotency._body_digest(req)
    assert digest == ""


def test_idempotency_digest_uses_cached_body_when_set():
    req = _make_request()
    req.state.cached_body = b'{"model": "gpt-4o"}'
    d1 = idempotency._body_digest(req)
    # Same payload -> same digest, even from a fresh request object.
    req2 = _make_request()
    req2.state.cached_body = b'{"model": "gpt-4o"}'
    assert d1 == idempotency._body_digest(req2)
    # Different payload -> different digest (detects replays).
    req3 = _make_request()
    req3.state.cached_body = b'{"model": "gpt-5"}'
    assert d1 != idempotency._body_digest(req3)


def test_main_registers_request_body_logging_middleware():
    classes = [m.cls for m in app.user_middleware]
    from eiraos.core.middleware import RequestBodyLoggingMiddleware
    assert RequestBodyLoggingMiddleware in classes
