import inspect
from unittest.mock import Mock

import pytest

from eiraos.api.v1 import chat
from eiraos.application.authorization import AuthorizationContext
from eiraos.application.provider_execution_policy import (
    ProviderPolicyDenied,
    authorize_provider_execution,
)
from eiraos.domains.agents.models import Bot
from eiraos.domains.governance.capabilities import (
    Capability,
    Principal,
    PrincipalType,
    decide_role_capability,
)


def _authorization(role: str = "member", organization_id: int = 7) -> AuthorizationContext:
    decision = decide_role_capability(
        role=role,
        capability=Capability.CONVERSATION_CREATE,
        principal_organization_id=organization_id,
        resource_organization_id=organization_id,
    )
    return AuthorizationContext(
        user=Principal(PrincipalType.USER, "42", organization_id),
        organization=Principal(PrincipalType.ORGANIZATION, str(organization_id), organization_id),
        role=role,
        decision=decision,
    )


def _bot(
    *, bot_id: int = 11, organization_id: int = 7, tool_scope: str = "standard",
    visibility: str = "private", provider: str = "openai", model: str = "gpt-4o",
    credential_scope: str = "organization",
) -> Bot:
    return Bot(
        id=bot_id,
        organization_id=organization_id,
        title="bot",
        provider=provider,
        model=model,
        tool_scope=tool_scope,
        bot_visibility=visibility,
        is_public=visibility == "public",
        credential_scope=credential_scope,
    )


def test_member_and_standard_bot_receive_provider_execute_only():
    permit = authorize_provider_execution(
        authorization=_authorization(), bot=_bot(), caller_organization_id=7,
    )
    assert permit.capability is Capability.PROVIDER_EXECUTE
    assert (permit.user_id, permit.organization_id, permit.bot_id) == (42, 7, 11)
    assert (permit.provider, permit.model) == ("openai", "gpt-4o")


@pytest.mark.parametrize("role,scope,reason", [
    ("viewer", "standard", "provider_capability_denied"),
    ("member", "unknown", "provider_capability_denied"),
])
def test_missing_user_or_bot_capability_fails_closed(role, scope, reason):
    with pytest.raises(ProviderPolicyDenied) as exc:
        authorize_provider_execution(
            authorization=_authorization(role),
            bot=_bot(tool_scope=scope),
            caller_organization_id=7,
        )
    assert exc.value.reason == reason


def test_private_cross_tenant_bot_is_denied():
    with pytest.raises(ProviderPolicyDenied) as exc:
        authorize_provider_execution(
            authorization=_authorization(),
            bot=_bot(organization_id=8),
            caller_organization_id=7,
        )
    assert exc.value.reason == "bot_not_accessible"


def test_public_bot_retains_owner_provenance_in_permit():
    permit = authorize_provider_execution(
        authorization=_authorization(),
        bot=_bot(organization_id=8, visibility="public", credential_scope="platform"),
        caller_organization_id=7,
    )
    assert permit.organization_id == 7
    assert permit.bot_organization_id == 8


def test_public_cross_tenant_bot_requires_platform_credentials():
    with pytest.raises(ProviderPolicyDenied) as exc:
        authorize_provider_execution(
            authorization=_authorization(),
            bot=_bot(organization_id=8, visibility="public", credential_scope="organization"),
            caller_organization_id=7,
        )
    assert exc.value.reason == "cross_tenant_credential_denied"


def test_provider_or_model_change_invalidates_existing_permit():
    bot = _bot()
    permit = authorize_provider_execution(
        authorization=_authorization(), bot=bot, caller_organization_id=7,
    )
    bot.model = "gpt-4.1"
    with pytest.raises(ProviderPolicyDenied) as exc:
        permit.assert_matches(bot=bot, caller_organization_id=7)
    assert exc.value.reason == "permit_scope_mismatch"


def test_tool_scope_change_invalidates_existing_permit():
    bot = _bot()
    permit = authorize_provider_execution(
        authorization=_authorization(), bot=bot, caller_organization_id=7,
    )
    bot.tool_scope = "elevated"
    with pytest.raises(ProviderPolicyDenied) as exc:
        permit.assert_matches(bot=bot, caller_organization_id=7)
    assert exc.value.reason == "permit_scope_mismatch"


@pytest.mark.asyncio
async def test_permit_mismatch_stops_before_secret_or_factory(monkeypatch):
    bot = _bot()
    permit = authorize_provider_execution(
        authorization=_authorization(), bot=bot, caller_organization_id=7,
    )
    secret = Mock()
    factory = Mock()
    monkeypatch.setattr(chat.SecretService, "resolve", secret)
    monkeypatch.setattr(chat.AIProviderFactory, "get_provider", factory)
    bot.id = 12
    with pytest.raises(ProviderPolicyDenied):
        await chat._provider_for_bot(bot, 7, permit)
    secret.assert_not_called()
    factory.assert_not_called()


def test_chat_policy_precedes_idempotency_budget_persistence_and_provider():
    source = inspect.getsource(chat.create_chat_completion)
    policy = source.index("authorize_provider_execution(")
    assert policy < source.index("begin_idempotency")
    assert policy < source.index("_execution_budget()")
    assert policy < source.index("prepare_exchange(")
    assert policy < source.index("_provider_for_bot(")


def test_verifier_selection_has_policy_but_no_secret_side_effect():
    source = inspect.getsource(chat._find_verifier_bot)
    assert "authorize_provider_execution(" in source
    assert "SecretService" not in source


def test_primary_and_both_verifier_paths_require_permits():
    source = inspect.getsource(chat.create_chat_completion)
    assert source.count("_provider_for_bot(") == 3
    assert source.count("verifier_permit") == 4
