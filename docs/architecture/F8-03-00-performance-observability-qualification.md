# F8-03 — Performance and observability qualification

## Invariants

- Every liveness response and request log carries the immutable release SHA.
- Staging verifies that the running SHA equals the built/promoted Git commit.
- After functional smoke, a bounded live gate executes 100 concurrent-scheduled
  liveness requests and 100 authenticated-boundary rejection requests.
- Release fails when any response has the wrong status, when error rate exceeds
  zero, or when either scenario exceeds 500 ms p95.
- The gate emits one machine-readable JSON report containing limits, release
  identity, error counts and p50/p95/max latency.

These defaults are release safety thresholds, not a capacity claim. Sustained
throughput and provider-backed chat load require environment-specific targets
and provider quotas during the final operational qualification.
