# F3-01 — Capability model

## Contract

Authority is represented by immutable, tenant-bound capability grants. The
principal types are `user`, `organization`, `bot`, and `execution`.

An execution never inherits ambient authority. Its effective capabilities are
the intersection of:

1. the authenticated user's current organization-role grant;
2. the bot's declared tool scope;
3. the capabilities explicitly requested for that execution.

## Invariants

- Unknown roles, capabilities, and bot scopes fail closed.
- A capability grant belongs to exactly one organization.
- Cross-tenant execution derivation is rejected.
- Capability collections are immutable.
- An execution cannot receive `secret:manage` or other control-plane authority
  through a bot scope.
- Role authority has one source: `domains.governance.capabilities`.

## Phase boundary

F3-01 defines the domain contract and moves the existing role matrix to it.
F3-02 will bind all application/HTTP operations to one authorization boundary.
F3-03 will make the full resource hierarchy structurally tenant-bound.
