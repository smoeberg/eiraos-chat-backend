# F5-03 — Context compaction

## Contract

When completed conversation history cannot be carried as raw messages, the
context boundary may replace the older omitted prefix with one deterministic,
bounded compaction artifact. Recent raw turns and the current prompt retain
priority.

The artifact is short-term context. It is not a message persisted to the
conversation ledger and is never promoted to persistent memory.

## Invariants

- Only tenant-bound, completed user/assistant history can be a source.
- Source loading is bounded; compaction cannot trigger an unbounded query.
- The artifact is deterministic for identical ordered source messages.
- It carries source message IDs and a SHA-256 digest of canonical source text.
- It is emitted with the `user` role and an explicit `untrusted=true` marker;
  conversation content can never become a system instruction.
- Raw recent turns take priority over compacted older history.
- Raw history plus compaction never exceeds the input/history budgets.
- If the compaction envelope cannot fit, the system safely falls back to the
  bounded raw suffix.
- Compaction has no database, provider, authorization or persistence access.

Compaction is deliberately extractive and deterministic. Provider-generated
summaries, durable summary rows and cross-conversation memory remain outside
F5-03.