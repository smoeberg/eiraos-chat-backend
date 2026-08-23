"""Provider secret resolution with explicit credential scope.

Secrets are never stored in plaintext on the Bot row; a Bot carries only a
``secret_reference`` handle. This service resolves that reference to the real
credential from the configured secret store.

Credential scope rules:
  - organization: only the bot owner org's secrets may be used
  - platform: platform-level keys (env) may be used
  - public bots must NOT silently use another tenant's org credentials for
    cross-tenant callers; they may use platform scope or caller must own the bot

Current backend: environment-based lookup (EIRAOS_PROVIDER_<REF>).
Production should swap the resolver for Vault / K8s Secret / cloud SM.
"""
from __future__ import annotations

import os
from fastapi import HTTPException, status


class SecretService:
    @staticmethod
    def resolve(
        bot_owner_org_id: int | None,
        secret_reference: str | None,
        platform_api_key: str | None,
        *,
        credential_scope: str = "organization",
        caller_org_id: int | None = None,
    ) -> str:
        """Return a usable provider API key for the given bot.

        Fails closed rather than leaking or guessing a key.
        """
        scope = (credential_scope or "organization").lower()

        # Cross-tenant guard: organization-scoped secrets only for same org
        if scope == "organization":
            if (
                caller_org_id is not None
                and bot_owner_org_id is not None
                and int(caller_org_id) != int(bot_owner_org_id)
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="This bot's credentials are not available cross-tenant.",
                )

        if secret_reference:
            env_key = f"EIRAOS_PROVIDER_{secret_reference.upper()}"
            value = os.getenv(env_key)
            if value:
                return value
            # Fallback only when platform scope is allowed
            if scope == "platform":
                value = os.getenv("EIRAOS_PROVIDER_API_KEY")
                if value:
                    return value
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="AI provider secret is not configured for this bot.",
            )

        if scope == "platform" and platform_api_key:
            return platform_api_key

        if scope == "platform":
            default = os.getenv("OPENAI_API_KEY") or os.getenv("EIRAOS_PROVIDER_API_KEY")
            if default:
                return default

        if platform_api_key and scope != "organization":
            return platform_api_key

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI provider secret is not configured for this bot.",
        )
