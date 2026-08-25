import asyncio

import pytest

from eiraos.application.chat_recovery import FailureCode
from eiraos.application.provider_failure_isolation import (
    IsolatedProviderFailure,
    ProviderFailureIsolation,
    ProviderFailureKind,
    require_text,
)
from eiraos.core.exceptions import EiraOSException


@pytest.mark.asyncio
async def test_successful_execution_returns_validated_result():
    async def operation():
        return "answer"

    result = await ProviderFailureIsolation().execute(operation(), 1, validate=require_text)
    assert result == "answer"


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["", None, {"content": "answer"}])
async def test_invalid_completion_output_fails_closed(value):
    async def operation():
        return value

    with pytest.raises(IsolatedProviderFailure) as caught:
        await ProviderFailureIsolation().execute(operation(), 1, validate=require_text)
    assert caught.value.kind is ProviderFailureKind.INVALID_RESPONSE
    assert caught.value.failure_code is FailureCode.PROVIDER_FAILURE


@pytest.mark.asyncio
async def test_timeout_cancels_operation_and_has_distinct_failure_code():
    cancelled = asyncio.Event()

    async def stalled():
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    with pytest.raises(IsolatedProviderFailure) as caught:
        await ProviderFailureIsolation().execute(stalled(), 0.01)
    assert caught.value.kind is ProviderFailureKind.TIMEOUT
    assert caught.value.failure_code is FailureCode.PROVIDER_TIMEOUT
    assert caught.value.response_status == 504
    assert cancelled.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,kind",
    [
        (EiraOSException("upstream", "credential-bearing detail", 502), ProviderFailureKind.UPSTREAM),
        (RuntimeError("sdk secret"), ProviderFailureKind.INTERNAL),
    ],
)
async def test_provider_exceptions_are_typed_and_sanitized(error, kind):
    async def operation():
        raise error

    with pytest.raises(IsolatedProviderFailure) as caught:
        await ProviderFailureIsolation().execute(operation(), 1)
    assert caught.value.kind is kind
    assert "credential" not in str(caught.value)
    assert "secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_cancellation_is_not_reclassified():
    async def operation():
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await ProviderFailureIsolation().execute(operation(), 1)


@pytest.mark.asyncio
async def test_partial_stream_is_preserved_then_failure_is_isolated_and_closed():
    closed = asyncio.Event()

    async def stream():
        try:
            yield "partial"
            raise RuntimeError("provider internals")
        finally:
            closed.set()

    isolated = ProviderFailureIsolation().stream(stream())
    assert await isolated.__anext__() == "partial"
    with pytest.raises(IsolatedProviderFailure) as caught:
        await isolated.__anext__()
    assert caught.value.kind is ProviderFailureKind.INTERNAL
    assert closed.is_set()


@pytest.mark.asyncio
async def test_invalid_stream_chunk_fails_closed_and_empty_chunks_are_ignored():
    async def stream():
        yield ""
        yield 42

    with pytest.raises(IsolatedProviderFailure) as caught:
        _ = [chunk async for chunk in ProviderFailureIsolation().stream(stream())]
    assert caught.value.kind is ProviderFailureKind.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_stream_cleanup_error_cannot_mask_classified_provider_failure():
    class BrokenStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise EiraOSException("upstream", "private", 502)

        async def aclose(self):
            raise RuntimeError("cleanup internals")

    with pytest.raises(IsolatedProviderFailure) as caught:
        _ = [chunk async for chunk in ProviderFailureIsolation().stream(BrokenStream())]
    assert caught.value.kind is ProviderFailureKind.UPSTREAM


def test_isolation_boundary_has_no_persistence_dependency():
    import inspect
    from eiraos.application import provider_failure_isolation

    source = inspect.getsource(provider_failure_isolation)
    assert "ChatPersistence" not in source
    assert "Idempotency" not in source
