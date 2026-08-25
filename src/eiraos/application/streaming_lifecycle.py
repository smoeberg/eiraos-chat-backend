"""F2-05 deterministic streaming lifecycle primitives."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator, Awaitable, Callable


class StreamEventKind(str, Enum):
    CHUNK = "chunk"
    HEARTBEAT = "heartbeat"
    END = "end"
    DISCONNECTED = "disconnected"
    LEASE_LOST = "lease_lost"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class StreamEvent:
    kind: StreamEventKind
    content: str | None = None


class StreamTerminal(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StreamFinalizer:
    """Apply at most one terminal transition for a stream execution."""

    def __init__(self, apply: Callable[[StreamTerminal, str], Awaitable[None]]) -> None:
        self._apply = apply
        self._lock = asyncio.Lock()
        self._terminal: StreamTerminal | None = None

    @property
    def terminal(self) -> StreamTerminal | None:
        return self._terminal

    async def finalize(self, terminal: StreamTerminal, content: str) -> bool:
        async with self._lock:
            if self._terminal is not None:
                return False
            # Claim the terminal state before side effects. If persistence later
            # fails, another exception path must not overwrite the chosen result.
            self._terminal = terminal
            await self._apply(terminal, content)
            return True


class StreamPump:
    """Multiplex provider chunks, SSE heartbeats, disconnects and lease loss."""

    def __init__(
        self,
        stream: AsyncIterator[str],
        *,
        is_disconnected: Callable[[], Awaitable[bool]],
        lease_lost: asyncio.Event | None,
        heartbeat_seconds: float,
        chunk_timeout_seconds: float,
        disconnect_poll_seconds: float = 0.1,
    ) -> None:
        self._stream = stream
        self._is_disconnected = is_disconnected
        self._lease_lost = lease_lost
        self._heartbeat_seconds = heartbeat_seconds
        self._chunk_timeout_seconds = chunk_timeout_seconds
        self._disconnect_poll_seconds = disconnect_poll_seconds
        self._chunk_task: asyncio.Task | None = None
        self._disconnect_task: asyncio.Task | None = None
        self._lease_task: asyncio.Task | None = None
        self._chunk_deadline: float | None = None
        self._closed = False

    async def _wait_for_disconnect(self) -> None:
        while True:
            if await self._is_disconnected():
                return
            await asyncio.sleep(self._disconnect_poll_seconds)

    async def next_event(self) -> StreamEvent:
        if self._closed:
            return StreamEvent(StreamEventKind.END)
        loop = asyncio.get_running_loop()
        if self._chunk_task is None:
            self._chunk_task = asyncio.create_task(self._stream.__anext__())
            self._chunk_deadline = loop.time() + self._chunk_timeout_seconds
        if self._disconnect_task is None:
            self._disconnect_task = asyncio.create_task(self._wait_for_disconnect())
        if self._lease_lost is not None and self._lease_task is None:
            self._lease_task = asyncio.create_task(self._lease_lost.wait())

        assert self._chunk_deadline is not None
        remaining = max(0.0, self._chunk_deadline - loop.time())
        timer = asyncio.create_task(asyncio.sleep(min(self._heartbeat_seconds, remaining)))
        waiters = {self._chunk_task, self._disconnect_task, timer}
        if self._lease_task is not None:
            waiters.add(self._lease_task)
        done, _ = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        if timer not in done:
            timer.cancel()
            await asyncio.gather(timer, return_exceptions=True)

        if self._disconnect_task in done:
            return StreamEvent(StreamEventKind.DISCONNECTED)
        if self._lease_task is not None and self._lease_task in done:
            return StreamEvent(StreamEventKind.LEASE_LOST)
        if self._chunk_task in done:
            task = self._chunk_task
            self._chunk_task = None
            self._chunk_deadline = None
            try:
                return StreamEvent(StreamEventKind.CHUNK, await task)
            except StopAsyncIteration:
                return StreamEvent(StreamEventKind.END)
        if loop.time() >= self._chunk_deadline:
            return StreamEvent(StreamEventKind.TIMEOUT)
        return StreamEvent(StreamEventKind.HEARTBEAT)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        tasks = [task for task in (self._chunk_task, self._disconnect_task, self._lease_task) if task]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        close = getattr(self._stream, "aclose", None)
        if close is not None:
            await close()

