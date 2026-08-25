# F7-02 — Authentication and session hardening

## Invariants

- New passwords are bounded to 12–128 characters and oversized login input
  fails closed instead of escaping the password verifier.
- Unknown, disabled and passwordless identities execute the same password
  verification path before returning the same generic HTTP 401 response.
- JWT verification requires expiry, issue time, unique ID, issuer, audience,
  subject, positive integer tenant/user IDs and a positive token version.
- Only explicit HMAC JWT algorithms are accepted and access-token lifetime is
  bounded to one day.
- Identity-bound operational endpoints verify current membership, enabled user
  state and token version before serving data.

F7-02 does not add refresh tokens or browser cookies. The API continues to use
short-lived bearer access tokens with database-backed revocation.
