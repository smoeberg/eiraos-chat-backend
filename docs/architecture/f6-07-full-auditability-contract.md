# F6-07 — Full Auditability Contract

Status: Implemented
Phase: F6-07

## Purpose

Every agent/tool execution decision MUST produce a correlated, machine-readable audit trail sufficient to reconstruct what happened without exposing secrets.

## Required audit events

The audit stream MUST represent, at minimum:

- run started
- planner decision
- authorization decision
- budget decision
- tool selected
- tool execution started
- tool execution completed or failed
- observation received
- terminal run outcome

## Event requirements

Every event MUST contain:

- correlation/run identifier
- event identifier
- event type
- timestamp
- actor/context identifier where available
- outcome/reason code where applicable
- stable schema version

Events MUST be append-only from the audit writer's perspective and MUST preserve event ordering for a single run.

## Security

Audit records MUST NOT contain credentials, authorization headers, raw secrets, or unredacted sensitive tool arguments/results. Redaction MUST happen before persistence.

## Failure semantics

If a required audit event cannot be durably recorded, the associated execution MUST fail closed unless the event is explicitly classified as non-critical by the contract.

## Scope

F6-07 defines auditability only. It does not change planning, authorization, budget, execution, or depth/timeout semantics.

## Acceptance criteria

1. All required lifecycle events have stable event types.
2. Events are correlated to a run and ordered within that run.
3. Events contain stable schema/version metadata and machine-readable outcomes.
4. Sensitive data is redacted before persistence.
5. Required audit-write failures fail closed.
6. Audit output is sufficient to reconstruct the execution path.

## Runtime implementation

`AgentAuditTrail` appends each critical event to `agent_audit_events` with a
unique run sequence, stable schema version and tenant/member binding. The F6-06
async loop requires an audit writer and records every planner, policy, budget,
tool, observation and terminal transition. Arguments/results are never emitted;
the writer additionally redacts sensitive keys before every commit. A failed
critical write raises `AgentAuditUnavailable` and prevents further execution.

Migration head: `012_agent_audit`.