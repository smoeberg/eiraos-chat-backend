# F2-02-00 — Usage & Budget Contract

## Purpose
Define the canonical usage and budget model before quota/cost enforcement is integrated into the chat execution path.

## Principles

- Rate limiting, quota enforcement, and cost budgeting are separate controls.
- F2-01 provider/model authorization answers whether an execution is allowed.
- F2-02 budget enforcement answers whether an allowed execution is affordable.
- Budget checks occur before provider execution.
- Verification executions consume the same budget as primary executions.
- Unknown or unavailable budget state fails closed.
- Usage records must never contain secrets or authorization headers.

## Enforcement scopes

User: requests, tokens, and cost per configured window.
Organization: tokens and cost per configured window.
Execution: maximum estimated tokens and maximum estimated cost.

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

A failed reservation must prevent provider execution. Reservations must be atomic.

## Verification

When verification is enabled, the reservation must cover both primary and verifier estimated cost before either provider call starts. Verification must never become an unmetered secondary execution.

## Storage responsibilities

- Redis: atomic hot-path counters/reservations.
- PostgreSQL: durable usage/audit history.

Production enforcement must not silently fall back to in-memory state.

## Out of scope

This clean F2-02 enforcement primitive does not yet wire the gate into `chat.py`. That integration is deliberately a separate change after the contract and negative tests are green.
