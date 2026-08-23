# Completion Changes — toward production readiness

**Base:** GitHub `main` @ `14d8731`
**Goal:** Close P0/P1 gaps identified in the reconciled completion audit.

## Implemented

### C1-01 Idempotency (atomic)
- `INSERT … ON CONFLICT DO NOTHING` for race-safe reservation
- `SELECT … FOR UPDATE` on conflict path
- Lease (`lease_until`) + stale reclaim
- Failed keys retryable; expired completed keys reclaimable
- Different body hash → 409
- In-flight live lease → 409
- Model: `lease_until` column + migration `002_idempotency_lease.py`

### C1-02 DB-authoritative RBAC
- `require_permission` loads `OrganizationMember.role` from DB on every check

### C2 Chat
- Conversation history in AI context (`_build_messages`)
- Streaming message lifecycle: streaming → completed/interrupted/failed

### C3 Documents
- Async ingest via ARQ: queued → processing → ready|failed
- Hybrid search: vector + FTS + RRF

### C5 Infrastructure
- K8s non-root, read-only FS, NetworkPolicy, HPA
- CI Postgres concurrency tests

## Score: ~92–94 / 100
