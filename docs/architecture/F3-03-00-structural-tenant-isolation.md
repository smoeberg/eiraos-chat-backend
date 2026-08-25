# F3-03 — Structural tenant isolation

## Contract

Tenant isolation is enforced by database relationships, not only by endpoint
filters. Invalid cross-tenant aggregates cannot be persisted.

```text
User + Organization membership
        ↓
Conversation ──→ Message
        ↓
Chat execution ──→ Usage / Idempotency
        ↑
Bot + owning organization
```

## Invariants

- A conversation owner must be a member of the conversation organization.
- A bot must belong to an existing organization.
- An execution's conversation and user must belong to its execution tenant.
- An execution's bot reference includes the bot owner's organization.
- Public cross-tenant bots retain their true owner as provenance; they are not
  relabelled as belonging to the caller's tenant.
- Message conversation/execution references include the message tenant.
- Usage and idempotency bindings cannot silently cross execution tenant/user
  scope.
- Existing rows are backfilled before new non-null columns are activated; an
  orphan aborts the migration rather than being guessed or deleted.

## Migration

Revision `007_tenant_isolation` adds composite uniqueness anchors, tenant-aware
foreign keys, `chat_executions.bot_organization_id`, and
`messages.organization_id`.

## Phase boundary

F3-03 supplies structural ownership. F3-04 will make policy enforcement timing
and coverage explicit for every provider path. F3-05 will persist decisions.
