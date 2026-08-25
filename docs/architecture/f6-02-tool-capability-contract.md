# F6-02 — Tool Capability Model Contract

Status: Contract
Phase: F6-02

## Purpose

Define a stable capability vocabulary for tools so later policy and authorization layers can reason about what a tool is capable of doing without coupling authorization to the registry.

## Capability identity

A capability MUST be represented by a stable, non-empty identifier using dot-separated segments.

Examples:

- `calendar.read`
- `calendar.write`
- `documents.read`
- `documents.write`
- `knowledge.search`

Capability identifiers MUST be:

- deterministic
- case-sensitive
- free of whitespace
- immutable once published

This phase does not define a global closed vocabulary. New capabilities may be introduced by later tool contracts, subject to validation rules.

## Tool declaration

A tool MAY declare one or more capabilities.

The capability declaration MUST be part of the tool's registered metadata and MUST be immutable after registration.

A tool with no capabilities is valid for F6-02, but it MUST NOT thereby acquire implicit permissions.

A capability declared by a tool describes what the tool can do; it does not grant any actor permission to perform that capability.

## Registry integration

The existing Tool Registry MUST expose declared capabilities as metadata.

Registry operations remain discovery-only:

- registering a capability does not authorize it
- retrieving a tool does not authorize it
- listing capabilities does not authorize them
- the registry MUST NOT inspect user identity or organization permissions

## Capability semantics

Capabilities describe the effective operation class of a tool, not individual users.

Read and write operations SHOULD use distinct capabilities where the operation has materially different security or side-effect characteristics.

For example:

- `calendar.read` MUST NOT imply `calendar.write`
- `documents.read` MUST NOT imply `documents.write`

No capability inheritance is defined by F6-02.

## Validation

The capability model MUST reject:

- empty identifiers
- identifiers containing whitespace
- identifiers containing empty dot-separated segments
- non-string capability values

Duplicate capabilities on a single tool MUST be normalized or rejected deterministically; the preferred contract is normalization to a unique immutable set.

## Security boundary

Capability declaration is descriptive metadata, not authorization.

Authorization is explicitly deferred to F6-03. A future policy layer MUST independently determine whether an actor may exercise a declared capability.

The capability model MUST NOT contain:

- user permissions
- organization permissions
- roles
- access tokens
- credentials
- policy decisions
- confirmation decisions

## Backward compatibility

Existing tools from F6-01 remain valid without capabilities. Adding capability metadata MUST NOT change existing registry lookup or execution behaviour.

## Acceptance criteria

1. Valid dot-separated capabilities can be declared on a tool.
2. Invalid capability identifiers are rejected deterministically.
3. Capability declarations are immutable after registration.
4. Duplicate capabilities have deterministic normalization semantics.
5. Capability metadata is discoverable through the registry.
6. A capability does not imply authorization.
7. Read and write capabilities are independent.
8. No F6-03 authorization logic is introduced.
