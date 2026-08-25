"""Shared, fail-closed HTTP semantics for provider adapters."""

from collections.abc import Callable
from typing import Any, TypeVar

import httpx

from eiraos.core.exceptions import EiraOSException

T = TypeVar("T")


def normalized_base_url(value: str) -> str:
    return value.rstrip("/")


def upstream_failure(provider: str, exc: Exception | None = None) -> EiraOSException:
    status = None
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
    suffix = f" (HTTP {status})" if status is not None else ""
    return EiraOSException(
        title="Upstream request failed",
        detail=f"{provider} request failed{suffix}.",
        status_code=502,
    )


def decode_completion(response: httpx.Response, provider: str, unpack: Callable[[Any], T]) -> T:
    try:
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise upstream_failure(provider, exc) from exc
    return unpack(payload)
