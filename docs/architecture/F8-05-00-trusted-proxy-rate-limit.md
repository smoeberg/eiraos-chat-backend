# F8-05 — Trusted proxy rate-limit identity

## Invariants

- Uvicorn proxy-header rewriting is disabled; the application owns the only
  forwarding trust decision used by rate limiting.
- An untrusted direct peer cannot change its identity with
  `X-Forwarded-For`; malformed chains fail closed to the peer address.
- For a trusted peer, the chain is validated as IP literals and traversed
  right-to-left across known proxies to the nearest untrusted client.
- IPv4 and IPv6 CIDRs are explicit. Production rejects missing/invalid values
  and networks that trust every address (`/0`).
- Staging requires environment-specific ingress CIDRs; manifests default only
  to loopback and therefore never silently trust a cluster-wide private range.

The same identity function backs global and auth endpoint limits. Correct CIDRs
must match observed ingress source addresses and are part of the live F8 gate.
