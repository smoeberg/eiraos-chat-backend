# F3-04 — Provider policy enforcement

## Contract

No provider secret may be resolved and no provider may be constructed or called
without an immutable execution permit. The permit binds:

- authenticated user and caller organization;
- current database role grant;
- `provider:execute` capability;
- bot identity, owner organization, visibility and tool scope;
- normalized provider and allowlisted model.

## Ordering

```text
identity / membership
→ conversation + bot ownership
→ provider execution policy
→ idempotency
→ budget
→ persistence
→ secret resolution
→ provider construction
→ provider execution
```

## Invariants

- `conversation:create` alone is not provider authority.
- Both the user role and bot scope must grant `provider:execute`.
- Unknown bot scopes fail closed.
- Private bots cannot cross tenants.
- A public bot permit retains its true owner organization as provenance.
- Changing bot, tenant, provider or model invalidates an issued permit.
- Permit validation occurs before secret resolution.
- Primary, streaming and both verifier paths use the same gate.
- The existing governed provider wrapper rechecks provider/model immediately
  before the upstream adapter call (defence in depth).

## Phase boundary

F3-04 enforces decisions before execution. F3-05 persists request → identity →
policy → decision → execution → result evidence.
