import pytest
from fastapi import HTTPException

from eiraos.application.providers.governed import GovernedAIProvider


class FakeProvider:
    def __init__(self):
        self.models = []

    async def generate_chat_completion(self, messages, model, temperature=0.7, max_tokens=1000, system_prompt=None):
        self.models.append(model)
        return "ok"


@pytest.mark.asyncio
async def test_execution_boundary_rejects_unapproved_model():
    fake = FakeProvider()
    governed = GovernedAIProvider(fake, "openai")
    with pytest.raises(HTTPException) as exc:
        await governed.generate_chat_completion(messages=[], model="privileged-model")
    assert exc.value.status_code == 403
    assert fake.models == []


@pytest.mark.asyncio
async def test_execution_boundary_forwards_authorized_model():
    fake = FakeProvider()
    governed = GovernedAIProvider(fake, "openai")
    result = await governed.generate_chat_completion(messages=[], model="gpt-4o")
    assert result == "ok"
    assert fake.models == ["gpt-4o"]
