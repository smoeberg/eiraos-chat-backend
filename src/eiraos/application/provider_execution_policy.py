"""F3-04 provider execution policy gate."""

from dataclasses import dataclass

from eiraos.application.authorization import AuthorizationContext
from eiraos.application.providers.policy import authorize_provider_model
from eiraos.domains.agents.models import Bot
from eiraos.domains.governance.capabilities import (
    ROLE_CAPABILITIES,
    Capability,
    CapabilitySet,
    Principal,
    PrincipalType,
    derive_execution_capabilities,
)


class ProviderPolicyDenied(PermissionError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ProviderExecutionPermit:
    user_id: int
    organization_id: int
    bot_id: int
    bot_organization_id: int
    provider: str
    model: str
    bot_tool_scope: str
    bot_visibility: str
    credential_scope: str
    capability: Capability = Capability.PROVIDER_EXECUTE

    def assert_matches(self, *, bot: Bot, caller_organization_id: int) -> None:
        try:
            actual_provider, actual_model = authorize_provider_model(bot.provider, bot.model)
        except Exception as exc:
            raise ProviderPolicyDenied("provider_model_denied") from exc
        actual = (
            caller_organization_id,
            getattr(bot, "id", None),
            getattr(bot, "organization_id", None),
            actual_provider,
            actual_model,
            (getattr(bot, "tool_scope", "") or "").strip().lower(),
            Bot.visibility(bot),
            (getattr(bot, "credential_scope", "") or "").strip().lower(),
        )
        expected = (
            self.organization_id,
            self.bot_id,
            self.bot_organization_id,
            self.provider,
            self.model,
            self.bot_tool_scope,
            self.bot_visibility,
            self.credential_scope,
        )
        if actual != expected:
            raise ProviderPolicyDenied("permit_scope_mismatch")


def authorize_provider_execution(
    *, authorization: AuthorizationContext, bot: Bot, caller_organization_id: int,
) -> ProviderExecutionPermit:
    """Issue least-privilege authority before secrets or providers are touched."""

    bot_id = getattr(bot, "id", None)
    bot_org_id = getattr(bot, "organization_id", None)
    if not isinstance(bot_id, int) or bot_id <= 0:
        raise ProviderPolicyDenied("invalid_bot_identity")
    if not isinstance(bot_org_id, int) or bot_org_id <= 0:
        raise ProviderPolicyDenied("invalid_bot_tenant")
    if authorization.organization_id != caller_organization_id:
        raise ProviderPolicyDenied("authorization_tenant_mismatch")
    if bot_org_id != caller_organization_id and Bot.visibility(bot) != "public":
        raise ProviderPolicyDenied("bot_not_accessible")
    credential_scope = (getattr(bot, "credential_scope", "") or "").strip().lower()
    if credential_scope not in {"organization", "platform"}:
        raise ProviderPolicyDenied("credential_scope_denied")
    if bot_org_id != caller_organization_id and credential_scope != "platform":
        raise ProviderPolicyDenied("cross_tenant_credential_denied")

    role_grants = ROLE_CAPABILITIES.get(authorization.role, frozenset())
    user_grant = CapabilitySet.create(authorization.user, role_grants)
    try:
        execution_grant = derive_execution_capabilities(
            user_grant=user_grant,
            bot_principal=Principal(PrincipalType.BOT, str(bot_id), bot_org_id),
            bot_scope=(getattr(bot, "tool_scope", "") or "").strip().lower(),
            requested={Capability.PROVIDER_EXECUTE},
            execution_id=f"provider-preflight:{caller_organization_id}:{bot_id}",
        )
    except (PermissionError, ValueError) as exc:
        # Public bots are allowed across tenants, but grant derivation remains
        # caller-tenant bound. Rebind only the bot execution principal; retain
        # its real owner separately in the permit provenance.
        if bot_org_id != caller_organization_id and Bot.visibility(bot) == "public":
            execution_grant = derive_execution_capabilities(
                user_grant=user_grant,
                bot_principal=Principal(PrincipalType.BOT, str(bot_id), caller_organization_id),
                bot_scope=(getattr(bot, "tool_scope", "") or "").strip().lower(),
                requested={Capability.PROVIDER_EXECUTE},
                execution_id=f"provider-preflight:{caller_organization_id}:{bot_id}",
            )
        else:
            raise ProviderPolicyDenied("execution_scope_denied") from exc
    if Capability.PROVIDER_EXECUTE not in execution_grant.capabilities:
        raise ProviderPolicyDenied("provider_capability_denied")

    try:
        provider, model = authorize_provider_model(bot.provider, bot.model)
    except Exception as exc:
        raise ProviderPolicyDenied("provider_model_denied") from exc
    return ProviderExecutionPermit(
        user_id=authorization.user_id,
        organization_id=caller_organization_id,
        bot_id=bot_id,
        bot_organization_id=bot_org_id,
        provider=provider,
        model=model,
        bot_tool_scope=(getattr(bot, "tool_scope", "") or "").strip().lower(),
        bot_visibility=Bot.visibility(bot),
        credential_scope=credential_scope,
    )
