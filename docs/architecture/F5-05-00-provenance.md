# F5-05 — Provenance

## Contract

Every durable memory item can answer where its information came from without
returning raw source content. Provenance resolution follows explicit memory or
message bindings and emits an ordered, tenant-bound graph.

## Invariants

- The root and every traversed memory source must be visible in the caller's
  organization and user/organization scope.
- Creation records authoritative actor, source type, source identity, target
  content digest and source content digest; caller metadata cannot override it.
- Content is bound with SHA-256 and checked again during resolution.
- Message nodes expose identity, role and digest, never message content.
- Traversal is bounded to 20 nodes and detects cycles.
- Missing, cross-tenant or corrupt sources terminate as unavailable or integrity
  failure without leaking the hidden source identity.
- Soft-deleted source memory may remain visible only as provenance for a still
  visible descendant; deleted items cannot be queried as roots.
- Provenance reads use `memory:read` and have no provider side effects.

The resolver describes lineage; it does not assert that remembered content is
factually true.