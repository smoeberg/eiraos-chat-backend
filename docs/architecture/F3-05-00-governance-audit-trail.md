# F3-05 — Durable governance audit trail

## Evidence chain

```text
request hash
→ authenticated identity / tenant / role
→ versioned policy + capability
→ allowed or denied decision
→ immutable permit fingerprint
→ execution binding
→ terminal result / failure code
```

## Invariants

- Prompt content and credentials are never stored in governance evidence.
- The request is content-bound with SHA-256.
- Allowed decisions record the exact permit fingerprint.
- Denied decisions are durable and immediately terminal.
- Audit persistence failure stops provider execution fail-closed.
- An allowed decision must match execution user and tenant before binding.
- Decision-to-execution binding uses a tenant-aware foreign key.
- Execution result and governance result finalize in the same transaction.
- Replays and preflight failures receive explicit terminal audit outcomes.
- Audit-required executions cannot finalize without linked evidence.

## Migration

Revision `008_governance_audit` creates `governance_decisions` and marks new
audited executions with `chat_executions.governance_audit_required`.

## Security boundary

The table contains identifiers, normalized policy inputs, hashes and result
metadata only. It intentionally excludes prompts, responses, API keys and raw
authorization tokens.
