# F2-06 — Chat persistence contract

Status: implemented contract

## Aggregate

One `ChatExecution` durably binds:

- tenant, user, conversation and bot
- request/correlation identity
- optional idempotency record and lease owner
- exactly one user message
- exactly one assistant message
- provider/model and usage/cost record
- execution lifecycle state

## Invariants

- An execution identity is replay-stable when an idempotency key is present.
- User message, assistant placeholder, execution and usage estimate commit together.
- The durable ledger commits before external provider/context preparation.
- `(execution_id, role)` is unique for messages; duplicate assistant rows are rejected.
- Assistant content, execution terminal state and idempotency response finalize in one transaction.
- Terminal execution state cannot be overwritten.
- Idempotency ownership is validated before any terminal mutation.
- The Alembic graph has one connected head from `0019` through F2-06.

Actual provider usage enrichment can update the existing usage record when
provider adapters expose usage metadata. Crash reconciliation remains F2-07.
