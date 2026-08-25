# F6-04 — Execution Budget Contract

Status: Contract
Phase: F6-04

## Purpose

Define a bounded execution budget for future agent/tool execution. The budget limits cumulative work and MUST be enforced before an execution step proceeds.

## Budget

A budget MUST contain finite limits for:

- maximum tool executions
- maximum execution time

A budget MAY contain additional resource limits later, but F6-04 does not require them.

## Semantics

- A missing or invalid budget MUST fail closed.
- A zero remaining execution allowance MUST deny the next execution.
- Budget consumption MUST be monotonic; consumed allowance MUST NOT increase again during a run.
- The authorization decision and execution budget are separate concerns: authorization answers whether an actor may use a capability; budget answers whether execution allowance remains.

## Atomicity

Checking and consuming an execution allowance MUST be atomic from the caller's perspective. Two concurrent execution attempts MUST NOT both consume the same final allowance.

## Time limit

The execution-time limit MUST be represented as a finite duration/deadline. The implementation MUST prevent execution from continuing after the budget deadline.

## Auditability

Budget decisions MUST expose machine-readable reason codes and remaining allowance suitable for audit. They MUST NOT contain secrets.

## Scope exclusions

F6-04 MUST NOT implement:

- tool selection
- planning
- authorization policy
- tool execution itself
- maximum agent depth/loop semantics (F6-06)

## Acceptance criteria

1. Finite execution and time limits are explicit.
2. Invalid/missing budgets fail closed.
3. Exhausted budgets deny further execution.
4. Consumption is monotonic.
5. Concurrent final-budget consumption is atomic.
6. Time limits are enforceable deadlines/durations.
7. Decisions expose audit-safe reason codes.
8. No planner, authorization, execution, or depth-loop behavior is introduced.
