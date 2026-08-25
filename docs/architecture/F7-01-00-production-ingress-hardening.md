# F7-01 — Production ingress and configuration hardening

## Audit findings

- Unbounded request buffering permitted memory exhaustion, including chunked
  requests without `Content-Length`.
- Production could silently use process-local rate limiting without Redis.
- CORS allowed localhost independently of deployment environment.
- Arbitrary request IDs were reflected and bound to structured logs.
- Host headers had no explicit allowlist.

## Invariants

- Request bodies are bounded while streaming and before buffering; declared and
  undeclared oversize requests return RFC 7807-style HTTP 413 responses.
- Invalid `Content-Length` fails with HTTP 400.
- Only bounded machine-safe request IDs are accepted; all others are replaced.
- Trace context is cleared after every request.
- CORS origins and trusted hosts come from validated settings.
- Production requires Redis-backed rate limiting, explicit HTTPS origins,
  explicit public hosts and disables synchronous ingest fallback.
- Unknown deployment environments and unreasonable body limits fail at boot.

F7-01 does not terminate TLS itself; HSTS and trusted proxy/TLS termination are
deployment concerns qualified later in F7.
