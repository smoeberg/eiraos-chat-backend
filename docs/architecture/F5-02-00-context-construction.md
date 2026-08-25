# F5-02 — Context construction

## Pipeline

Context construction is a pure application boundary:

1. load tenant-bound completed user/assistant history newest-first;
2. resolve the selected model context window from the governed F4 catalog;
3. reserve output tokens;
4. account for mandatory system prompt and current user prompt;
5. select the newest whole-message history suffix within the remaining policy budget;
6. emit chronological messages plus the current prompt.

The system prompt is returned separately because the provider contract already
has a dedicated `system_prompt` parameter. It is never duplicated inside the
message list. The current prompt is always appended, even when it is identical
to the previous user message.

## Invariants

- Mandatory context that cannot fit fails before provider execution.
- The current execution's already-persisted user row is excluded from history.
- History selection never splits a message or exceeds the token budget.
- A selected suffix never begins with an orphan assistant turn.
- Cancelled, failed, streaming, system and unknown-role rows are excluded.
- Selection is deterministic and exposes selected message IDs and truncation
  count as provenance metadata.
- The builder has no database, provider, authorization or persistence access.

F5-02 uses deterministic character-based token estimates, consistent with the
current accounting contract. Context compaction is intentionally deferred to
F5-03.