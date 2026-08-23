"""Sprint 6: chat idempotency wiring + protected /metrics."""
from fastapi import FastAPI


def test_metrics_endpoint_requires_auth():
    """/metrics must be gated (not anonymous) to avoid leaking internal metrics."""
    import eiraos.main as m
    from fastapi.routing import APIRoute

    app: FastAPI = m.app
    route = next(r for r in app.routes if getattr(r, "path", None) == "/metrics")
    qualnames = {d.call.__qualname__ for d in route.dependant.dependencies}
    assert "get_current_user" in qualnames, f"metrics not authed: {qualnames}"


def test_chat_completion_request_has_idempotency_key_field():
    from eiraos.api.v1.chat import ChatCompletionRequest
    assert "idempotency_key" in ChatCompletionRequest.model_fields


def test_chat_completions_endpoint_has_request_param():
    """The non-streaming completions endpoint must accept a Request for idempotency."""
    import inspect
    from eiraos.api.v1 import router, chat

    route = next(
        r for r in chat.router.routes
        if getattr(r, "path", "") == "/chat/completions" and "POST" in (getattr(r, "methods", None) or ())
    )
    sig = inspect.signature(route.endpoint)
    assert "request" in sig.parameters, "completions endpoint missing Request param for idempotency"


def test_idempotency_begins_before_provider_nonstream():
    """Assert the non-streaming completion path reserves idempotency."""
    import inspect
    import eiraos.api.v1.chat as chat
    src = inspect.getsource(chat.create_chat_completion)
    assert "begin_idempotency" in src
    assert "complete_idempotency" in src
