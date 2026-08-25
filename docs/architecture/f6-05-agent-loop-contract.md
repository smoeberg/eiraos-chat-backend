# F6-05 — Agent Loop Contract

Status: Contract
Phase: F6-05

## Purpose

Define the bounded control loop that coordinates planning, policy, tool selection, execution, and observation.

## Loop

The loop follows:

`Conversation → Planner → Policy → Tool selection → Tool execution → Observation → next step`

The loop MUST preserve conversation context and MUST make each transition explicit.

## Step semantics

Each iteration MUST have an explicit state and outcome. A tool execution may produce an observation; an authorization denial or budget denial is an outcome and MUST NOT be treated as successful execution.

The loop MUST stop when:

- the planner produces a terminal answer/state
- policy denies continuation
- no valid next action exists
- an execution budget denies continuation
- an execution error is returned

## Separation of concerns

F6-05 coordinates existing boundaries. It MUST NOT redefine:

- capability metadata (F6-02)
- authorization policy (F6-03)
- execution budget semantics (F6-04)
- maximum depth/timeout policy (F6-06)

The loop MUST NOT bypass authorization or budget checks.

## Observations

Every completed tool step MUST yield an explicit observation or explicit failure outcome before the next iteration.

Observations MUST be treated as untrusted tool output and MUST NOT silently mutate policy or authorization state.

## Determinism and auditability

Each iteration MUST have a correlation/run identifier and a monotonically increasing step number. The state transition and outcome MUST be auditable without storing secrets.

## Failure behavior

Unexpected exceptions MUST terminate the current run safely. Partial execution MUST NOT be represented as successful completion.

## Acceptance criteria

1. The loop follows the explicit planner/policy/selection/execution/observation sequence.
2. Each iteration has explicit state and outcome.
3. Authorization and budget gates cannot be bypassed.
4. The loop has explicit terminal conditions.
5. Tool observations are explicit and untrusted.
6. Every iteration is auditable with run ID and step number.
7. Unexpected failures terminate safely.
8. F6-06 depth/timeout semantics remain separate.
