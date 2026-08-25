# F3-02 — Authorization boundary

## Contract

Every chat request crosses one application authorization boundary before
idempotency, budget reservation, persistence, or provider execution.

The signed identity selects a user and organization context. Current database
membership supplies the authoritative role. The F3-01 capability model then
produces a typed, tenant-bound decision and authorization context.

## Ordering

```text
authenticated identity
→ active tenant membership
→ application capability decision
→ resource lookup
→ idempotency
→ budget
→ persistence
→ provider
```

## Invariants

- JWT role claims never grant authority.
- Missing membership and unknown roles/capabilities fail closed.
- A resource tenant mismatch is denied by the same boundary.
- The HTTP adapter exposes a generic denial and does not leak internal reason
  codes.
- Chat has one capability dependency rather than a route gate plus a parallel
  identity dependency.
- Authorization produces no budget, persistence, or provider side effect.

## Deferred

F3-03 binds every concrete conversation, bot, execution, message and document
resource into the structural tenant hierarchy. F3-05 persists decision evidence.
