# F7 Gate — Production hardening audit

## Scope qualified

- Security: bounded ingress, explicit hosts/CORS, production Redis rate limits,
  strict JWT/session claims, password policy and authoritative revocation.
- Reliability: provider/persistence recovery inherited from F2/F4, bounded
  readiness probes, deterministic resource cleanup and database disposal.
- Observability: request correlation, structured completion/failure latency,
  protected metrics, redaction and dependency health state.
- Supply chain: every PR audits the installed Python dependency graph; weekly
  update monitoring covers Python, GitHub Actions and Docker.
- Build tooling requires `setuptools>=83.0.0`, remediating PYSEC-2026-3447
  discovered by the first gate run.

## Gate evidence

- F7-01 focused gate: 29 passed; full suite: 503 passed / 6 skipped.
- F7-02 focused gate: 49 passed; full suite: 511 passed / 6 skipped.
- F7-03 focused gate: 33 passed; full suite: 517 passed / 6 skipped.
- Final F7 gate includes all phase contracts, production qualification,
  recovery and non-external concurrency regressions.

Postgres concurrency and dependency vulnerability checks remain mandatory
GitHub CI jobs because they require service/network facilities unavailable in
the local isolated runner. F8 performs load/performance, restart and release
qualification; those are not claimed by this gate.
