from eiraos.api.v1.chat import _verifier_bot_accessible
from eiraos.domains.agents.models import Bot


def _bot(*, organization_id: int, is_public: bool = False) -> Bot:
    return Bot(
        organization_id=organization_id,
        title="test verifier",
        provider="openai",
        model="test-model",
        bot_visibility="public" if is_public else "private",
        is_public=is_public,
    )


def test_verifier_bot_must_belong_to_callers_organization() -> None:
    candidate = _bot(organization_id=2, is_public=True)

    assert _verifier_bot_accessible(candidate, 1) is False


def test_verifier_bot_from_callers_organization_is_allowed() -> None:
    candidate = _bot(organization_id=1, is_public=False)

    assert _verifier_bot_accessible(candidate, 1) is True


def test_public_verifier_bot_from_same_organization_is_allowed() -> None:
    candidate = _bot(organization_id=1, is_public=True)

    assert _verifier_bot_accessible(candidate, 1) is True
