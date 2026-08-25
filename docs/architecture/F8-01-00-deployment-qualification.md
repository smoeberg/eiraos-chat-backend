# F8-01 — Deployment qualification contract

## Invariants

- The release image contains the application and its exact Alembic migration
  chain, runs as UID 10001 and exposes process liveness only to Docker.
- API and worker receive the same production database, Redis, secret, CORS and
  trusted-host contract; required Redis configuration never degrades silently.
- Provider keys are optional at boot and fail closed only when a provider is
  actually selected.
- Kubernetes runs both API and ARQ worker without privilege escalation, with a
  read-only root filesystem and explicit resource bounds.
- API and worker have explicit network policies; the worker accepts no ingress
  and can reach only DNS, PostgreSQL, Redis and HTTPS provider endpoints.
- Staging creates the exact secret keys consumed by the manifests and promotes
  the same SHA-tagged image to API, worker and migration job.

F8-01 qualifies deployability, not live cluster behavior. Restart, load,
latency and rollback exercises remain later F8 gates.
