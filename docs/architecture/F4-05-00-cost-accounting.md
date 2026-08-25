# F4-05 — Cost accounting

## Contract

Provider accounting is an append-only ledger bound to `ChatExecution` and its
tenant. Budget reservations and post-execution usage are distinct records:

- `reservation` records retain the preflight token/cost reservation;
- `primary` records identify the primary provider/model invocation;
- `verification` records identify an optional verifier invocation separately.

Each usage entry carries input, output and total tokens, cost, attempt number,
measurement source and pricing-catalog revision. Final usage rows are appended
in the same transaction as the exactly-once terminal execution transition.

## Measurement provenance

The canonical F4-01 text interface does not expose provider-reported usage.
F4-05 therefore records a deterministic character-based token estimate with
`usage_source=estimated`; it does not mislabel that value as provider-reported.
Prices come from the immutable F4-03 catalog and are stored as `Decimal` USD
values. Unknown models fail closed rather than receiving an invented price.

Retries use the durable execution attempt number. Replays do not append usage,
and exactly-once finalization prevents duplicate accounting rows.
