"""Shared, fail-closed HTTP semantics for provider adapters."""

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar

import httpx
import structlog

from eiraos.core.exceptions import EiraOSException

T = TypeVar("T")
logger = structlog.get_logger()
TRANSIENT_STATUSES = frozenset({429, 502, 503, 504})
TRANSIENT_EXCEPTIONS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)


def normalized_base_url(value: str) -> str:
    return value.rstrip("/")


def retry_delay(response: httpx.Response | None, fallback: float, maximum: float) -> float:
    if response is None:
        return min(fallback, maximum)
    value = response.headers.get("Retry-After", "").strip()
    if not value:
        return min(fallback, maximum)
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            seconds = (when - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            seconds = fallback
    return min(max(0.0, seconds), maximum)


async def post_with_retry(
    client: httpx.AsyncClient, url: str, *, provider: str,
    max_attempts: int | None = None, backoff_seconds: float | None = None,
    max_retry_after_seconds: float | None = None,
    sleep=asyncio.sleep, **request_kwargs,
) -> httpx.Response:
    """Retry bounded pre-response completion calls; never used by streams."""
    from eiraos.core.config import settings

    attempts = settings.PROVIDER_HTTP_MAX_ATTEMPTS if max_attempts is None else max_attempts
    backoff = settings.PROVIDER_HTTP_BACKOFF_SECONDS if backoff_seconds is None else backoff_seconds
    retry_after_cap = (
        settings.PROVIDER_HTTP_MAX_RETRY_AFTER_SECONDS
        if max_retry_after_seconds is None else max_retry_after_seconds
    )
    if not 1 <= attempts <= 3:
        raise ValueError("provider HTTP attempts must be between 1 and 3")
    if backoff < 0 or retry_after_cap < 0:
        raise ValueError("provider retry delays must be non-negative")
    for attempt in range(1, attempts + 1):
        response = None
        try:
            response = await client.post(url, **request_kwargs)
        except TRANSIENT_EXCEPTIONS:
            if attempt >= attempts:
                raise
        else:
            if response.status_code not in TRANSIENT_STATUSES or attempt >= attempts:
                return response
        delay = retry_delay(response, backoff * (2 ** (attempt - 1)), retry_after_cap)
        if response is not None:
            await response.aclose()
        logger.warning(
            "provider_http_retry", provider=provider, attempt=attempt,
            max_attempts=attempts, status_code=response.status_code if response is not None else None,
            delay_ms=round(delay * 1000),
        )
        await sleep(delay)
    raise RuntimeError("provider retry loop exhausted")


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
