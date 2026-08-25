import asyncio
from unittest.mock import AsyncMock

import pytest

from eiraos.application.streaming_lifecycle import (
    StreamEventKind,
    StreamFinalizer,
    StreamPump,
    StreamTerminal,
)


async def _chunks(values):
    for value in values:
        yield value


@pytest.mark.asyncio
async def test_pump_streams_chunks_then_end():
    pump = StreamPump(
        _chunks(["a", "b"]), is_disconnected=AsyncMock(return_value=False),
        lease_lost=None, heartbeat_seconds=1, chunk_timeout_seconds=2,
    )
    assert (await pump.next_event()).content == "a"
    assert (await pump.next_event()).content == "b"
    assert (await pump.next_event()).kind is StreamEventKind.END
    await pump.aclose()


@pytest.mark.asyncio
async def test_heartbeat_does_not_reset_original_chunk_timeout():
    async def stalled():
        await asyncio.sleep(1)
        yield "late"

    pump = StreamPump(
        stalled(), is_disconnected=AsyncMock(return_value=False), lease_lost=None,
        heartbeat_seconds=0.01, chunk_timeout_seconds=0.035,
    )
    heartbeats = 0
    while True:
        event = await pump.next_event()
        if event.kind is StreamEventKind.TIMEOUT:
            break
        assert event.kind is StreamEventKind.HEARTBEAT
        heartbeats += 1
        assert heartbeats < 10
    assert heartbeats >= 2
    await pump.aclose()


@pytest.mark.asyncio
async def test_disconnect_and_lease_loss_interrupt_pending_provider():
    async def stalled():
        await asyncio.sleep(1)
        yield "late"

    disconnected = AsyncMock(side_effect=[False, True])
    pump = StreamPump(
        stalled(), is_disconnected=disconnected, lease_lost=None,
        heartbeat_seconds=1, chunk_timeout_seconds=2, disconnect_poll_seconds=0,
    )
    assert (await pump.next_event()).kind is StreamEventKind.DISCONNECTED
    await pump.aclose()

    lost = asyncio.Event()
    pump = StreamPump(
        stalled(), is_disconnected=AsyncMock(return_value=False), lease_lost=lost,
        heartbeat_seconds=1, chunk_timeout_seconds=2,
    )
    lost.set()
    assert (await pump.next_event()).kind is StreamEventKind.LEASE_LOST
    await pump.aclose()


@pytest.mark.asyncio
async def test_close_cancels_pending_read_and_closes_provider_stream():
    closed = asyncio.Event()

    async def stalled():
        try:
            await asyncio.sleep(1)
            yield "late"
        finally:
            closed.set()

    pump = StreamPump(
        stalled(), is_disconnected=AsyncMock(return_value=False), lease_lost=None,
        heartbeat_seconds=0.01, chunk_timeout_seconds=2,
    )
    assert (await pump.next_event()).kind is StreamEventKind.HEARTBEAT
    await pump.aclose()
    assert closed.is_set()


@pytest.mark.asyncio
async def test_finalization_is_exactly_once_even_when_first_apply_fails():
    apply = AsyncMock(side_effect=RuntimeError("db unavailable"))
    finalizer = StreamFinalizer(apply)
    with pytest.raises(RuntimeError, match="db unavailable"):
        await finalizer.finalize(StreamTerminal.COMPLETED, "answer")
    assert finalizer.terminal is StreamTerminal.COMPLETED
    assert not await finalizer.finalize(StreamTerminal.FAILED, "answer")
    apply.assert_awaited_once()
