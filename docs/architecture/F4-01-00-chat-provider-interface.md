# F4-01 — Canonical ChatProvider interface

## Contract

Every provider exposed to the application implements:

```text
ChatProvider
├── complete(...)
├── stream(...)
├── models()
└── capabilities()
```

`complete` and `stream` are the only application execution methods. `models`
returns an immutable deterministic tuple. `capabilities` returns the frozen
`ProviderCapabilities` value object.

## Invariants

- Factory output satisfies the runtime-checkable `ChatProvider` protocol.
- The governed wrapper preserves the same interface.
- Governed model discovery is the intersection of adapter catalog and current
  server policy.
- Unsupported capabilities default to `False`.
- A capability is advertised only when the current adapter implements it.
- Application chat and verification paths use canonical method names.
- Legacy generation method names remain adapter-only compatibility aliases and
  are not part of the canonical protocol.

## Current implemented capabilities

All three current HTTP adapters implement text completion and text streaming.
They do not yet implement the contract-level vision, tools, structured output,
reasoning or embeddings operations, so those flags remain false.

## Phase boundary

F4-01 defines the common interface. F4-02 can now add adapters without changing
chat orchestration. F4-03 will expand capability discovery and model metadata.
