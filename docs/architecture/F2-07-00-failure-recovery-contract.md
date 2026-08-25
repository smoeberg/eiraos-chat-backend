# F2-07 — Failure and recovery contract

## Boundary

F2-07 defines how an already-authorized chat execution fails and how it may be
retried. Authorization, idempotency reservation and budget rejection remain
preflight gates and still run before provider execution.

## Invariants

- Non-streaming provider execution has one total server-side deadline.
- Streaming retains the F2-05 per-chunk deadline and persists partial output on
  timeout, provider failure or cancellation.
- Every durable terminal failure records a server-defined failure code and a
  retryability decision.
- A retry requires the same tenant, user, conversation, bot and idempotency
  record plus current lease-token ownership.
- Retry count is bounded by the execution's immutable `max_attempts` value.
- Each new attempt adds its token/cost reservation to the execution's existing
  usage record.
- A reclaimed lease may reset an abandoned `prepared` or `streaming` execution;
  this is recorded as `process_crash` before the next attempt starts.
- A completed execution is never reopened.
- The same user and assistant message rows remain bound to every attempt. A
  retry never inserts a duplicate assistant row.
- Database finalization failure leaves the durable state non-terminal; after the
  lease expires, the normal replay path is the only recovery path.
- Expired idempotency records detach with `ON DELETE SET NULL`; a replacement
  record ID creates a new execution identity without deleting the old ledger.

## Failure policy

| Code | HTTP | Retryable | Durable execution |
|---|---:|:---:|:---:|
| `provider_timeout` | 504 | yes | yes |
| `provider_failure` | 502 | yes | yes |
| `database_failure` | 503 | yes | only when the database can commit it |
| `idempotency_lost` | 409 | yes | fenced by lease ownership |
| `client_cancelled` | 499 | yes | yes |
| `process_crash` | 500 | yes | recorded during owned recovery |
| `retry_exhausted` | 409 | no | yes |
| `budget_rejected` | 429 | no | no provider/execution side effect |
| `idempotency_conflict` | 409 | no | no provider side effect |

## Crash recovery

There is deliberately no hidden background retry. After a process crash, the
idempotency lease expires. A replay of the same request may then reclaim that
lease, lock the existing execution aggregate and start the next bounded attempt.
This avoids executing a provider call without an explicit client request and a
current fencing token.

## Deferred

Provider-native idempotency keys and an operator-driven stale-execution sweep are
production-hardening concerns. They do not weaken the F2-07 rule that only a
current lease owner can mutate or resume an execution.
