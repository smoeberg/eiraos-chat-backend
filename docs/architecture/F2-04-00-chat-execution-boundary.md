# F2-04 — Chat execution boundary

Status: implemented contract

## Invariant

Every chat completion follows this order:

1. request schema validation
2. tenant-scoped authorization
3. idempotency reservation or replay
4. usage-budget reservation
5. provider/context preparation
6. request persistence
7. provider execution (complete or stream)
8. result persistence
9. idempotency finalization

No later step may run when an earlier step fails. A completed idempotency replay
short-circuits before budget reservation, provider initialization and writes.

## Ownership

`ChatExecutionBoundary` owns steps 2–6 and exposes an immutable prepared
execution. The HTTP adapter maps domain failures to HTTP and owns response
formatting. Provider calls remain behind the prepared execution. Streaming
lease/cancellation/finalization mechanics are deliberately F2-05 scope.

## Failure semantics

- authorization failure: no idempotency, budget, provider or persistence side effects
- idempotency conflict: no budget, provider or persistence side effects
- budget denial/unavailability: no provider or message persistence side effects
- provider preparation failure: an acquired idempotency lease is released by the adapter
- replay: cached response is returned without charging or writing again

