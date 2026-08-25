"""F4-04 provider failure isolation boundary."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from enum import Enum
from typing import TypeVar

from eiraos.application.chat_recovery import FailureCode, provider_with_timeout
from eiraos.core.exceptions import EiraOSException

T = TypeVar("T")


class ProviderFailureKind(str, Enum):
    TIMEOUT = "timeout"
    UPSTREAM = "upstream"
    INVALID_RESPONSE = "invalid_response"
    INTERNAL = "internal"


class IsolatedProviderFailure(Exception):
    """Sanitized provider failure safe to cross into application orchestration."""

    def __init__(self, kind: ProviderFailureKind):
        self.kind = kind
        self.failure_code = (
            FailureCode.PROVIDER_TIMEOUT
            if kind is ProviderFailureKind.TIMEOUT
            else FailureCode.PROVIDER_FAILURE
        )
        self.response_status = 504 if kind is ProviderFailureKind.TIMEOUT else 502
        detail = "AI provider timed out." if kind is ProviderFailureKind.TIMEOUT else "AI provider could not fulfil the request."
        super().__init__(detail)


def require_text(value: T) -> T:
    if not isinstance(value, str) or not value:
        raise IsolatedProviderFailure(ProviderFailureKind.INVALID_RESPONSE)
    return value


class ProviderFailureIsolation:
    """Normalize provider behavior without reading or mutating execution state."""

    async def execute(
        self,
        operation: Awaitable[T],
        timeout_seconds: float,
        *,
        validate: Callable[[T], T] | None = None,
    ) -> T:
        try:
            result = await provider_with_timeout(operation, timeout_seconds)
            return validate(result) if validate is not None else result
        except asyncio.CancelledError:
            raise
        except IsolatedProviderFailure:
            raise
        except asyncio.TimeoutError as exc:
            raise IsolatedProviderFailure(ProviderFailureKind.TIMEOUT) from exc
        except EiraOSException as exc:
            raise IsolatedProviderFailure(ProviderFailureKind.UPSTREAM) from exc
        except Exception as exc:
            raise IsolatedProviderFailure(ProviderFailureKind.INTERNAL) from exc

    async def stream(self, provider_stream: AsyncIterator[str]) -> AsyncIterator[str]:
        try:
            async for chunk in provider_stream:
                if not isinstance(chunk, str):
                    raise IsolatedProviderFailure(ProviderFailureKind.INVALID_RESPONSE)
                if chunk:
                    yield chunk
        except asyncio.CancelledError:
            raise
        except IsolatedProviderFailure:
            raise
        except EiraOSException as exc:
            raise IsolatedProviderFailure(ProviderFailureKind.UPSTREAM) from exc
        except Exception as exc:
            raise IsolatedProviderFailure(ProviderFailureKind.INTERNAL) from exc
        finally:
            close = getattr(provider_stream, "aclose", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    # Cleanup is best-effort and cannot replace the classified
                    # provider failure already crossing this boundary.
                    pass
