# F6 Gate — Governed agent/tool runtime

## Gate finding

F6-01 through F6-07 existed as individually tested contracts, but no composed
runtime bound discovery, tenant authority, authorization, budget, dispatch,
limits and durable audit into one mandatory execution path. The phase could not
pass while callers had to compose those boundaries themselves.

## Remediation

`GovernedAgentRuntime` is now the single F6 execution boundary. It:

- resolves planner selections only through `ToolRegistry`;
- rejects tenant mismatch, unknown tools, undeclared and ungranted capabilities;
- issues an in-run permit only after authorization and consumes it at dispatch;
- validates declared input before calling an executor and output afterwards;
- passes explicit actor/organization/capability context to each executor;
- requires exactly one cancellable async executor per registered tool;
- applies the F6 budget, depth, timeout and durable audit boundaries; and
- keeps registry metadata deeply immutable.

## Gate result

The gate passes when focused negative tests, the full suite, PostgreSQL
migrations and CI are green with no open P0/P1 findings. Tool implementations
and product-specific agent endpoints remain explicit later feature work; they
must call this runtime rather than compose an alternate dispatch path.