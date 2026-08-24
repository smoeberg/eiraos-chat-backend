# F2-02-00 — Usage & Budget Contract

## Purpose
Define the canonical usage and budget model before quota/cost enforcement is implemented.

## Principles

- Rate limiting, quota enforcement, and cost budgeting are separate controls.
- F2-01 provider/model authorization answers whether an execution is allowed.
- F2-02 budget enforcement answers whether an allowed execution is affordable.
- Budget checks occur before provider execution.
- Verification executions consume the same budget as primary executions.
- Unknown or unavailable budget state fails closed.
- Usage records must never contain secrets or authorization headers.

## Canonical usage record

Each provider execution is associated with:

- `request_id`
- `execution_id`
- `user_id`
- `organization_id`
- `provider`
- `model`
- `input_tokens`
- `output_tokens`
- `total_tokens`
- `estimated_cost`
- `actual_cost`
- `verification`
- `timestamp`

`estimated_cost` is used for pre-execution reservation. `actual_cost` is recorded after provider completion.

## Enforcement scopes

### User

- requests per configured time window
- tokens per configured time window
- cost per configured time window

### Organization

- tokens per configured time window
- cost per configured time window

### Execution

- maximum estimated input/output tokens
- maximum estimated cost

## Execution flow

```text
request
  -> authentication / tenant context
  -> provider + model authorization (F2-01)
  -> estimate execution cost
  -> reserve user quota
  -> reserve organization budget
  -> execute primary provider call
  -> execute verifier when enabled
  -> record actual usage/cost
  -> release unused reservation
```

All reservations must be atomic. A failed reservation must prevent provider execution.

## Verification

When verification is enabled, budget reservation must account for the primary execution and the verifier execution before either provider call starts. Verification cannot create an unmetered secondary execution.

## Storage responsibilities

- Redis: atomic counters/reservations and hot-path enforcement.
- PostgreSQL: durable usage/audit history and reporting.

The enforcement path must not depend on a best-effort in-memory fallback in production.

## Fail-closed rules

Deny execution when:

- the applicable budget policy cannot be resolved;
- required tenant identity is unavailable;
- a reservation cannot be atomically established;
- estimated execution cost exceeds the execution limit;
- user quota is exhausted;
- organization budget is exhausted.

## Out of scope

This contract does not yet implement quotas, pricing tables, Redis keys, database migrations, or API endpoints. Those are subsequent F2-02 implementation steps.
