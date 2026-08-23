# Postgres idempotency concurrency tests

## What they prove

| Test | Assertion |
|------|-----------|
| `test_concurrent_begin_only_one_processing` | 16 parallel `begin_idempotency` → exactly **1** `processing`, **15** HTTP 409 |
| `test_different_payload_same_key_conflicts` | Same key, different body → 409 |
| `test_completed_replay_after_finish` | After complete, parallel replays all get `completed` + cached body |
| `test_stale_lease_allows_reclaim` | Expired lease can be reclaimed |

## Run locally

```bash
# Start Postgres (example)
docker run -d --name eiraos-pg \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=eiraos_test \
  -p 5432:5432 postgres:16-alpine

export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/eiraos_test
export PYTHONPATH=src

pytest tests/test_idempotency_postgres_concurrency.py -v
```

Without `DATABASE_URL` the tests **skip** (unit suite still green).

## CI

`.github/workflows/ci.yml` starts a `postgres:16` service and runs this file as a dedicated step.
