# F4-03 — Capability discovery

## Contract

Discovery is a read-only intersection of three authorities:

1. the versioned server-side model catalog describes native model features,
   context window and standard text-token prices;
2. provider policy determines which catalog models may be exposed;
3. the concrete adapter determines which native features are actually usable.

`ProviderModelMetadata.capabilities` is the effective intersection. Native
features remain visible separately in `native_capabilities`, so the system can
distinguish “the model supports tools” from “this adapter currently implements
tools”. Discovery never grants authorization and never contacts an upstream
provider.

## Invariants

- Provider aliases are normalized through the canonical provider policy.
- Discovery uses the governed provider returned by `AIProviderFactory`.
- Only models present in both policy output and the immutable catalog appear.
- Unknown models fail closed and receive no inferred metadata.
- Metadata and pricing values are immutable and carry a catalog revision.
- Credentials and provider instances never appear in discovery results.
- Pricing is USD per one million standard text tokens; special tiers, caching,
  batch discounts and regional prices are outside this contract.
- Updating model availability or pricing requires an explicit catalog revision.
- Results are deterministic for a given catalog, policy and adapter state.

F4-03 does not enable vision, tools, structured output, reasoning or embeddings.
Those capabilities become effective only when an adapter implements them.
Provider runtime failure isolation remains F4-04.
