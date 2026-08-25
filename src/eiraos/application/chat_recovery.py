"""F2-07 failure classification and bounded recovery policy."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, TypeVar


T = TypeVar("T")


class FailureCode(str, Enum):
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_FAILURE = "provider_failure"
    DATABASE_FAILURE = "database_failure"
    IDEMPOTENCY_LOST = "idempotency_lost"
    BUDGET_REJECTED = "budget_rejected"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    CLIENT_CANCELLED = "client_cancelled"
    PROCESS_CRASH = "process_crash"
    RETRY_EXHAUSTED = "retry_exhausted"
    CONTEXT_REJECTED = "context_rejected"


@dataclass(frozen=True)
class FailurePolicy:
    response_status: int
    retryable: bool


_POLICIES = {
    FailureCode.PROVIDER_TIMEOUT: FailurePolicy(504, True),
    FailureCode.PROVIDER_FAILURE: FailurePolicy(502, True),
    FailureCode.DATABASE_FAILURE: FailurePolicy(503, True),
    FailureCode.IDEMPOTENCY_LOST: FailurePolicy(409, True),
    FailureCode.BUDGET_REJECTED: FailurePolicy(429, False),
    FailureCode.IDEMPOTENCY_CONFLICT: FailurePolicy(409, False),
    FailureCode.CLIENT_CANCELLED: FailurePolicy(499, True),
    FailureCode.PROCESS_CRASH: FailurePolicy(500, True),
    FailureCode.RETRY_EXHAUSTED: FailurePolicy(409, False),
    FailureCode.CONTEXT_REJECTED: FailurePolicy(422, False),
}


def failure_policy(code: FailureCode) -> FailurePolicy:
    return _POLICIES[code]


async def provider_with_timeout(awaitable: Awaitable[T], timeout_seconds: float) -> T:
    """Apply one total deadline to a non-streaming provider operation."""
    if timeout_seconds <= 0:
        raise ValueError("provider timeout must be positive")
    return await asyncio.wait_for(awaitable, timeout=timeout_seconds)