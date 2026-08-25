# F2-05 — Streaming lifecycle

Status: implemented contract

## Invariants

- A provider read retains its original timeout deadline across SSE heartbeats.
- Heartbeats are emitted while the provider is idle, not only after chunks.
- Client disconnect and idempotency lease loss interrupt a pending provider read.
- Provider streams are explicitly closed on every exit path.
- Exactly one terminal state is claimed: `completed`, `failed`, or `cancelled`.
- A later exception must never overwrite an already claimed terminal state.

## Lifecycle

```text
prepared → streaming → completed
                     ↘ failed
                     ↘ cancelled
```

`StreamPump` owns event multiplexing and provider cleanup. `StreamFinalizer`
owns the single terminal transition. Database atomicity and durable recovery
remain F2-06 and F2-07 scope.

