# F6-03 — Tool Authorization Contract

Status: Contract
Phase: F6-03

## Purpose

Define the authorization boundary between an actor, a tool capability, and tool execution. F6-03 decides whether an actor MAY exercise a declared capability. It does not execute tools or implement the agent loop.

## Authorization decision

Authorization MUST produce an explicit allow/deny decision for an actor attempting to exercise a capability on a tool.

A capability declaration from F6-02 is descriptive metadata and MUST NOT itself grant permission.

## Inputs

An authorization check MAY consider:

- actor identity
- organization/tenant context
- tool identity
- declared capability
- relevant policy context

Credentials/tokens are authentication concerns and MUST NOT be stored in tool metadata.

## Default deny

Unknown actors, unknown tools, undeclared capabilities, missing policy, and invalid authorization requests MUST resolve to deny.

Authorization MUST NOT infer permission from capability names, read/write ordering, or tool registration alone.

## Separation of concerns

The authorization layer MUST NOT:

- execute tools
- select tools
- mutate tool registry metadata
- create capabilities
- perform agent planning
- consume execution budget
- make confirmation decisions

Tool execution is deferred to later F6 phases.

## Determinism and auditability

For the same authorization input and policy state, the decision MUST be deterministic.

An authorization decision MUST expose a machine-readable reason/code suitable for audit logging. It MUST NOT expose secrets or credentials.

## Security boundary

Authorization is the security boundary between capability declaration and execution permission.

F6-03 does not define a global role hierarchy or policy language. Policy representation MAY be introduced by implementation, provided it preserves this contract.

## Acceptance criteria

1. Authorization decisions are explicit allow/deny outcomes.
2. Capability declarations do not imply authorization.
3. Default behavior is deny when authorization context is insufficient.
4. Authorization can distinguish actors and policy context.
5. Unknown/undeclared capabilities are denied.
6. Decisions are deterministic for identical inputs and policy state.
7. Decisions expose audit-safe reason codes.
8. No tool execution, planning, registry mutation, budget, or agent-loop behavior is introduced.
