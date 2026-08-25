# F5-01 — Conversation state

## Aggregate contract

`ConversationAggregate` is the authoritative lifecycle model for a
conversation. It owns:

- tenant and owner identity;
- normalized title;
- `active` or `archived` lifecycle;
- optimistic version;
- creation, update and archive timestamps;
- rename, archive, reopen and execution-admission transitions.

All transitions return a new immutable aggregate and increment the version.
Archiving is idempotent. An archived conversation rejects new chat executions
until an explicit reopen transition occurs.

## Persistence boundary

The ORM row stores lifecycle, version and archive time. Mapping functions are
the only translation between ORM state and the domain aggregate. SQLAlchemy
uses the aggregate version as an optimistic concurrency token, while database
check constraints reject invalid lifecycle/version values.

The existing DELETE route now archives instead of physically deleting history.
Tenant/owner lookup remains structural, and chat calls the domain admission
rule before budget reservation, provider setup or message persistence.

F5-01 does not yet define context construction, compaction or memory. Those
remain F5-02 through F5-04.
