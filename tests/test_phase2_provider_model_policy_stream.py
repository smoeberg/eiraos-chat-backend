import pytest
from fastapi import HTTPException

from eiraos.application.providers.governed import GovernedAIProvider


class FakeStreamProvider:
    def __init__(self):
        self.models = []

    async def stream_chat_completion(self, messages, model, temperature=0.7, max_tokens=1000, system_prompt=None):
        self.models.append(model)
        yield "ok"


@pytest.mark.asyncio
async def test_stream_execution_boundary_rejects_unapproved_model():
    fake = FakeStreamProvider()
    governed = GovernedAIProvider(fake, "openai")
    with pytest.raises(HTTPException) as exc:
        async for _ in governed.stream_chat_completion(messages=[], model="privileged-model"):
            pass
    assert exc.value.status_code == 403
    assert fake.models == []
