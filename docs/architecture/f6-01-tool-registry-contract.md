# F6-01 — Tool Registry Contract

Status: Contract
Phase: F6-01

## Purpose

Define the application-layer contract for registering and discovering agent tools.

## Scope

This phase defines metadata and registry behaviour only. It does not authorize users, execute tools, enforce budgets, or implement the agent loop.

## Tool contract

A tool MUST expose:

- `name`: stable, non-empty identifier.
- `version`: explicit tool contract version.
- `description`: human-readable purpose.
- `input_schema`: machine-readable schema describing accepted input.
- `output_schema`: machine-readable schema describing produced output.

Tool metadata MUST be immutable after registration.

A tool MAY expose implementation-specific execution behaviour, but the registry MUST NOT invoke it.

## Registry contract

The registry MUST provide:

- `register(tool)` — register a tool.
- `get(name)` — retrieve a registered tool by stable name.
- `list()` — return all registered tools in deterministic name order.

### Registration invariants

- Empty or whitespace-only names are invalid.
- Tool names are unique within a registry.
- Registering an existing name is rejected; registration MUST NOT silently replace an existing tool.
- Registry state is process-local unless a later phase explicitly introduces persistence.

### Lookup invariants

- Unknown tool names return a defined `ToolNotFound` error.
- `get()` never executes a tool.
- `list()` never exposes implementation secrets or credentials.

## Explicit non-responsibilities

F6-01 MUST NOT implement:

- authorization or policy decisions
- capability evaluation
- user or organization access checks
- execution budgets
- timeouts
- tool execution
- planner behaviour
- audit persistence

These concerns belong to subsequent F6 phases.

## Security boundary

Registry contents are descriptive metadata and MUST be treated as untrusted input by future planner components. Registration does not imply permission to execute a tool.

## Acceptance criteria

1. A valid tool can be registered once.
2. Duplicate names are rejected deterministically.
3. Registered tools can be retrieved by name.
4. Unknown names produce a defined not-found error.
5. Listing is deterministic.
6. Registry operations have no execution side effects.
7. No authorization semantics are embedded in the registry.
