# Postgres idempotency concurrency tests

Requires DATABASE_URL=postgresql+asyncpg://...

```bash
pytest tests/test_idempotency_postgres_concurrency.py -v
```

Without DATABASE_URL the tests skip. CI starts postgres:16 automatically.
