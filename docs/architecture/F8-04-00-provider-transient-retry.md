# F8-04 — Provider transient retry contract

## Invariants

- Only non-streaming completion HTTP calls retry, within the already-authorized
  execution and its existing idempotency, budget and persistence bindings.
- Default attempts are bounded to two; configuration cannot exceed three.
- Retryable conditions are connect/read timeout and HTTP 429/502/503/504.
  Authentication, validation, ordinary client errors and HTTP 500 fail once.
- Backoff is exponential and `Retry-After` is honored only up to a configured
  cap. Logs contain provider, attempt, status and delay—never URL or secret.
- The application-level provider timeout remains the single total deadline and
  cancels both a pending request and retry sleep.
- Streaming never uses this helper; after stream opening or any emitted chunk,
  failure crosses the existing recovery boundary without an implicit replay.

Retries do not create new execution attempts or reservation/message rows.
Failed pre-response provider calls normally contain no billable usage; durable
accounting remains attached to the successful/terminal execution result.
