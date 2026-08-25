import pytest
from fastapi import HTTPException

from eiraos.application.providers.factory import AIProviderFactory
from eiraos.application.providers.governed import GovernedAIProvider
from eiraos.application.providers.policy import authorize_provider_model


class FakeProvider:
    def __init__(self):
        self.models = []

    async def complete(self, messages, model, temperature=0.7, max_tokens=1000, system_prompt=None):
        self.models.append(model)
        return "ok"

    async def stream(self, messages, model, temperature=0.7, max_tokens=1000, system_prompt=None):
        self.models.append(model)
        yield "ok"


def test_supported_provider_is_constructible():
    provider = AIProviderFactory.get_provider("openai", "sentinel")
    assert isinstance(provider, GovernedAIProvider)


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError):
        AIProviderFactory.get_provider("not-allowed-provider", "sentinel")


def test_allowed_provider_model_pair_is_authorized():
    assert authorize_provider_model("openai", "gpt-4o") == ("openai", "gpt-4o")


def test_unknown_model_is_rejected():
    with pytest.raises(HTTPException) as exc:
        authorize_provider_model("openai", "arbitrary-unapproved-model")
    assert exc.value.status_code == 403


def test_unknown_provider_is_rejected_by_policy():
    with pytest.raises(HTTPException) as exc:
        authorize_provider_model("not-allowed-provider", "anything")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_execution_boundary_rejects_unapproved_model():
    fake = FakeProvider()
    governed = GovernedAIProvider(fake, "openai")
    with pytest.raises(HTTPException) as exc:
        await governed.generate_chat_completion(messages=[], model="privileged-model")
    assert exc.value.status_code == 403
    assert fake.models == []


@pytest.mark.asyncio
async def test_execution_boundary_forwards_only_authorized_model():
    fake = FakeProvider()
    governed = GovernedAIProvider(fake, "openai")
    result = await governed.generate_chat_completion(messages=[], model="gpt-4o")
    assert result == "ok"
    assert fake.models == ["gpt-4o"]


@pytest.mark.asyncio
async def test_stream_execution_boundary_rejects_unapproved_model():
    fake = FakeProvider()
    governed = GovernedAIProvider(fake, "openai")
    with pytest.raises(HTTPException) as exc:
        async for _ in governed.stream_chat_completion(messages=[], model="privileged-model"):
            pass
    assert exc.value.status_code == 403
    assert fake.models == []
