"""Provider secret resolution.

Secrets are never stored in plaintext on the Bot row; a Bot carries only a
``secret_reference`` handle. This service resolves that reference to the real
credential from the configured secret store.

Current backend: environment-based lookup (EIRAOS_PROVIDER_<REF>). A production
deployment should swap the resolver for a real Secret Manager client without
changing the route handlers.
"""
from __future__ import annotations

import os
from fastapi import HTTPException, status


class SecretService:
    @staticmethod
    def resolve(bot_owner_org_id: int, secret_reference: str | None,
                platform_api_key: str | None) -> str:
        """Return a usable provider API key for the given bot.

        - If the bot references a platform-level credential, return the platform key.
        - Otherwise resolve the reference from the environment.
        - Fails closed (HTTP 500) rather than leaking or guessing a key.
        """
        if secret_reference:
            env_key = f"EIRAOS_PROVIDER_{secret_reference.upper()}"
            value = os.getenv(env_key)
            if value:
                return value
            value = os.getenv("EIRAOS_PROVIDER_API_KEY")
            if value:
                return value
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="AI provider secret is not configured for this bot.",
            )
        if platform_api_key:
            return platform_api_key
        default = os.getenv("OPENAI_API_KEY") or os.getenv("EIRAOS_PROVIDER_API_KEY")
        if default:
            return default
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI provider secret is not configured for this bot.",
        )
