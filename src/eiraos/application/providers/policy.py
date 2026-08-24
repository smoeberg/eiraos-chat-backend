import os

from fastapi import HTTPException, status

# Explicit server-side execution policy. Client input never extends this set.
DEFAULT_PROVIDER_MODELS: dict[str, frozenset[str]] = {
    "openai": frozenset({"gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini"}),
    "anthropic": frozenset({"claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"}),
    "google": frozenset({"gemini-1.5-pro", "gemini-1.5-flash"}),
}

PROVIDER_ALIASES = {"claude": "anthropic", "gemini": "google"}


def _configured_models(provider: str) -> frozenset[str]:
    key = f"EIRAOS_ALLOWED_MODELS_{provider.upper()}"
    raw = os.getenv(key)
    if raw is None:
        return DEFAULT_PROVIDER_MODELS.get(provider, frozenset())
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def normalize_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    normalized = PROVIDER_ALIASES.get(normalized, normalized)
    if normalized not in DEFAULT_PROVIDER_MODELS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="AI provider is not allowed.")
    return normalized


def authorize_provider_model(provider: str, model: str) -> tuple[str, str]:
    normalized_provider = normalize_provider(provider)
    normalized_model = model.strip()
    if not normalized_model or normalized_model not in _configured_models(normalized_provider):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="AI model is not allowed for this provider.")
    return normalized_provider, normalized_model
