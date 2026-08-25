# F7-03 — Reliability and observability hardening

## Invariants

- Request correlation and security headers wrap all application ingress
  boundaries, including body-size and trusted-host rejections.
- Every completed request emits its status and monotonic duration under the
  request ID, method and path context; failures emit only exception type.
- Health probes expose dependency state without exception text and always
  close their Redis client, including timeout and failure paths.
- Application shutdown disposes the database engine.
- Production disables interactive OpenAPI and ReDoc surfaces.

Liveness remains process-only. Readiness checks database and configured Redis
with bounded timeouts and returns HTTP 503 when either required dependency is
unavailable.
