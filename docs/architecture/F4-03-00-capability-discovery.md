# F4-03 — Capability discovery

## Contract

Capability discovery is a read-only application service over the governed provider boundary.

It returns deterministic model metadata containing:

- normalized provider name;
- the model name exposed by the governed provider catalog;
- the immutable `ProviderCapabilities` value object.

The discovery service never exposes provider credentials or provider instances and never performs an upstream generation request.

## Invariants

- model discovery uses the governed provider returned by `AIProviderFactory`;
- models filtered by current provider/model policy are not returned;
- capability flags come from the concrete adapter implementation;
- unsupported capabilities remain `False`;
- discovery is deterministic for a given governed provider state.

## Phase boundary

F4-03 defines model/capability discovery. It does not add provider execution features. Tool, vision, structured-output and reasoning execution remain separate capability work.
