# F4-04 — Provider failure isolation

## Contract

Every provider completion, verification and stream crosses
`ProviderFailureIsolation` before orchestration observes its result. The
boundary converts provider-specific behavior into a small typed vocabulary:

- timeout;
- upstream failure;
- invalid response;
- internal provider/SDK failure.

Timeouts remain distinguishable from other failures. Provider messages,
credentials, payloads and SDK details never cross the boundary. Task
cancellation is propagated unchanged and provider streams are closed on every
exit path.

## State isolation

The boundary has no persistence, idempotency, budget or authorization
dependency. It returns a value or raises one sanitized typed failure;
orchestration alone decides the terminal execution transition. A partial stream
may be persisted by the existing exactly-once finalizer, but a provider cannot
directly mutate or finalize execution state.

Retries and provider failover are not performed inside this boundary. F4-05
owns execution-linked usage and cost accounting.
