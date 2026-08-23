"""Provider secret resolution with explicit credential scope.

Secrets are never stored in plaintext on the Bot row; a Bot carries only a
``secret_reference`` handle. This service resolves that reference to the real
credential from the configured secret store.

Credential scope rules:
  - organization: requires verified caller and bot-owner organization context
  - platform: platform-level keys (env) may be used

Current backend: environment-based lookup (EIRAOS_PROVIDER_<REF>).
Production should swap the resolver for Vault / K8s Secret / cloud SM.
"""
from __future__ import annotations

import os
import re

from fastapi import HTTPException, status


_ALLOWED_SCOPES = frozenset({"organization", "platform"})
_SECRET_REFERENCE_RE = re.compile(r"[A-Za-z0-9_-]{1,100}")


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

        Organization-scoped credentials fail closed unless both the bot owner
        and authenticated caller organization are present and identical.
        Organization scope never falls back to platform credentials.
        """
        scope = (credential_scope or "").strip().lower()
        if scope not in _ALLOWED_SCOPES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Unsupported credential scope.",
            )

        if scope == "organization":
            if bot_owner_org_id is None or caller_org_id is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Organization credential requires verified tenant context.",
                )
            if int(caller_org_id) != int(bot_owner_org_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="This bot's credentials are not available cross-tenant.",
                )

        if secret_reference is not None:
            if not _SECRET_REFERENCE_RE.fullmatch(secret_reference):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid secret reference.",
                )
            env_key = f"EIRAOS_PROVIDER_{secret_reference.upper()}"
            value = os.getenv(env_key)
            if value:
                return value
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

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI provider secret is not configured for this bot.",
        )
