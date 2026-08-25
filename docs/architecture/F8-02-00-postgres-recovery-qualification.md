# F8-02 — PostgreSQL integrity, concurrency and recovery qualification

## Invariants

- Migrated PostgreSQL rejects cross-tenant message bindings and a second
  assistant row for the same execution.
- Two concurrent terminal transitions serialize on the execution row and
  produce exactly one winner, one assistant and one idempotency result.
- Recovery after a simulated streaming-process crash retains the original
  execution/messages, clears partial assistant content, increments the durable
  attempt and records `process_crash`.
- A second recovery beyond `max_attempts` atomically terminates execution and
  idempotency as `retry_exhausted`.

These tests run only in the dedicated CI PostgreSQL job after `alembic upgrade
head`; SQLite/unit simulations remain fast feedback, not release evidence.
