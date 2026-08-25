"""F2-04 application boundary for deterministic chat preflight execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Generic, TypeVar

TAuthorized = TypeVar("TAuthorized")
TProvider = TypeVar("TProvider")


@dataclass(frozen=True)
class IdempotencyReservation:
    key: str | None
    lease_token: str | None
    cached_response: dict[str, Any] | None = None
    record_id: int | None = None

    @property
    def is_replay(self) -> bool:
        return self.cached_response is not None


@dataclass(frozen=True)
class PreparedChatExecution(Generic[TAuthorized, TProvider]):
    authorized: TAuthorized | None
    provider_context: TProvider | None
    idempotency: IdempotencyReservation
    cached_response: dict[str, Any] | None = None

    @property
    def is_replay(self) -> bool:
        return self.cached_response is not None


class ChatExecutionBoundary(Generic[TAuthorized, TProvider]):
    """Order side-effecting preflight operations and short-circuit replays."""

    def __init__(
        self,
        *,
        authorize: Callable[[], Awaitable[TAuthorized]],
        reserve_idempotency: Callable[[], Awaitable[IdempotencyReservation]],
        reserve_budget: Callable[[TAuthorized], None],
        prepare_provider: Callable[[TAuthorized], Awaitable[TProvider]],
        persist_request: Callable[[TAuthorized], Awaitable[None]],
    ) -> None:
        self._authorize = authorize
        self._reserve_idempotency = reserve_idempotency
        self._reserve_budget = reserve_budget
        self._prepare_provider = prepare_provider
        self._persist_request = persist_request

    async def prepare(self) -> PreparedChatExecution[TAuthorized, TProvider]:
        authorized = await self._authorize()
        idem = await self._reserve_idempotency()
        if idem.is_replay:
            return PreparedChatExecution(
                authorized=None,
                provider_context=None,
                idempotency=idem,
                cached_response=idem.cached_response,
            )
        self._reserve_budget(authorized)
        await self._persist_request(authorized)
        provider_context = await self._prepare_provider(authorized)
        return PreparedChatExecution(
            authorized=authorized,
            provider_context=provider_context,
            idempotency=idem,
        )
