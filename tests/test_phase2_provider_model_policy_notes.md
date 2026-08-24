# F2-01 Provider/Model Policy

The provider factory now returns a governed execution wrapper. Both streaming and non-streaming chat calls validate the provider/model pair immediately before invoking the upstream adapter.

Default model policy is explicit and server-side. Deployments may replace a provider's default model set through `EIRAOS_ALLOWED_MODELS_<PROVIDER>`.

Client payloads cannot extend this policy.
