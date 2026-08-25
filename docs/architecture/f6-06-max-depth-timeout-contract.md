# F6-06 — Maximum Execution Depth / Timeout Contract

Status: Contract
Phase: F6-06

## Purpose

Define hard safety bounds for the agent loop so a run cannot continue indefinitely.

## Maximum execution depth

Every agent run MUST have a finite maximum execution depth.

- The depth counts completed tool-execution steps in the current run.
- A step MUST NOT execute when the maximum depth has already been reached.
- Reaching the limit MUST produce a terminal, machine-readable outcome.
- The limit MUST NOT be increased by the agent itself.

## Timeout

Every agent run MUST have a finite execution deadline.

- The deadline is established before the run begins.
- A step MUST NOT begin after the deadline.
- A running step MUST have an enforceable timeout boundary supplied by the execution layer.
- Timeout MUST produce a terminal, machine-readable outcome.

## Fail closed

Missing, non-finite, negative, or otherwise invalid depth/timeout configuration MUST fail closed before execution starts.

## Auditability

Depth and timeout termination MUST expose machine-readable reason codes and the observed depth/deadline context without secrets.

## Separation of concerns

F6-06 controls hard run bounds only. It does not define:

- tool selection
- authorization
- execution budget allowance
- planner behavior
- tool implementation

## Acceptance criteria

1. Maximum depth is finite and enforced before execution.
2. Maximum depth cannot be raised by the agent.
3. Timeout is finite and established before execution.
4. Execution cannot begin after deadline.
5. Running execution has an enforceable timeout boundary.
6. Invalid configuration fails closed.
7. Termination is terminal and audit-safe.
