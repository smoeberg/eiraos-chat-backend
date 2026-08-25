# F5-04 — Memory Contract

Status: Contract
Phase: F5-04

## Purpose

Define explicit memory boundaries so information is never implicitly promoted between conversation history, short-term context, persistent memory, and user/org knowledge.

## Memory classes

### Conversation history

The canonical record of messages/events belonging to a conversation. It is scoped to the conversation and is not persistent memory by implication.

### Short-term context

Ephemeral context assembled for the current task/run. It may be derived from conversation history or other permitted sources and expires with its declared scope/lifetime.

### Persistent memory

Information intentionally stored for reuse across conversations. Creation or update MUST be explicit and attributable to a memory operation.

### User/org knowledge

Knowledge owned or governed by the user or organization and available according to its access policy. It is distinct from personal persistent memory and MUST retain its ownership/scope.

## Promotion rules

- No automatic promotion from conversation history to persistent memory.
- No automatic promotion from short-term context to persistent memory.
- No automatic promotion from user memory to org knowledge or vice versa.
- Any promotion MUST be an explicit operation with actor, target class, reason, and provenance metadata.

## Scope and isolation

Every memory item MUST have an explicit class and scope. Reads MUST respect that scope. A memory item MUST NOT be returned merely because it is semantically relevant if the caller is not authorized for its scope.

## Lifecycle

Each class MUST define retention/lifetime semantics appropriate to its scope. Short-term context MUST be disposable; persistent memory MUST be explicitly deletable; user/org knowledge MUST follow its governing ownership and retention rules.

## Provenance boundary

Every persistent memory or user/org knowledge item MUST retain enough source metadata to support F5-05 provenance queries. Conversation history and short-term context MUST remain distinguishable as source classes.

## Acceptance criteria

1. Four memory classes are explicit and distinguishable.
2. Each item has class and scope.
3. Cross-class promotion is explicit and auditable.
4. No implicit promotion occurs.
5. Reads enforce scope/ownership.
6. Lifecycle/retention is class-aware.
7. Persistent and knowledge entries preserve provenance metadata.
