import io
from types import SimpleNamespace

import pytest

from eiraos.api.v1.chat import ChatCompletionRequest, _build_messages
from eiraos.application.business_features import (
    VERIFIED_BADGE,
    VERIFICATION_SYSTEM_PROMPT,
    build_knowledge_system_context,
    verify_answer,
)
from eiraos.domains.documents.file_service import (
    MAX_UPLOAD_BYTES,
    extract_text,
    safe_extension,
    validate_upload,
    write_upload,
)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeDB:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _stmt):
        return FakeResult(self.rows)


class FakeProvider:
    def __init__(self, response='{"status":"PASS","reason":"looks good"}'):
        self.response = response
        self.calls = []

    async def generate_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return self.response

    async def stream_chat_completion(self, **kwargs):
        yield self.response


def test_chat_request_accepts_verify_and_knowledge_scope():
    request = ChatCompletionRequest(
        conversation_id=1,
        bot_id=2,
        prompt="Question",
        verify=True,
        knowledge_scope="hr",
    )
    assert request.verify is True
    assert request.knowledge_scope == "hr"


def test_chat_request_rejects_unknown_fields():
    with pytest.raises(Exception):
        ChatCompletionRequest(
            conversation_id=1,
            bot_id=2,
            prompt="Question",
            unknown=True,
        )


@pytest.mark.asyncio
async def test_history_is_cross_bot_and_ordered():
    rows = [
        SimpleNamespace(id=3, role="assistant", content="Answer from bot B", status="completed"),
        SimpleNamespace(id=2, role="user", content="Question for bot B", status="completed"),
        SimpleNamespace(id=1, role="assistant", content="Answer from bot A", status="completed"),
    ]
    messages = await _build_messages(
        FakeDB(rows), 10, "new prompt", "system", max_history=40, history_token_budget=1000
    )
    assert [m["content"] for m in messages] == [
        "system", "Answer from bot A", "Question for bot B", "Answer from bot B", "new prompt"
    ]


@pytest.mark.asyncio
async def test_verification_sends_original_prompt_and_primary_answer():
    provider = FakeProvider()
    result = await verify_answer(
        primary_answer="42",
        original_prompt="What is the answer?",
        verifier=provider,
        model="verifier-model",
    )
    assert result.endswith(VERIFIED_BADGE)
    assert result.verified is True
    assert result.status == "PASS"
    assert provider.calls[0]["model"] == "verifier-model"
    messages = provider.calls[0]["messages"]
    assert "What is the answer?" in messages[0]["content"]
    assert "42" in messages[1]["content"]
    assert provider.calls[0]["system_prompt"] == VERIFICATION_SYSTEM_PROMPT


def test_knowledge_context_is_delimited_and_prioritized():
    context = build_knowledge_system_context([
        {"content": "Internal policy says X", "metadata": "HR"},
        {"content": "Internal policy says Y", "metadata": "Finance"},
    ])
    assert context is not None
    assert "Virksomhedens interne viden har prioritet" in context
    assert "<knowledge_context>" in context
    assert "Internal policy says X" in context
    assert "</knowledge_context>" in context


def test_empty_knowledge_context_is_none():
    assert build_knowledge_system_context([]) is None


def test_file_extension_validation():
    assert safe_extension("guide.md") == ".md"
    assert validate_upload("guide.md", 10) == ".md"
    with pytest.raises(ValueError):
        validate_upload("script.exe", 10)
    with pytest.raises(ValueError):
        validate_upload("guide.txt", MAX_UPLOAD_BYTES + 1)


def test_text_and_markdown_extraction():
    assert extract_text(b"hello\nworld", ".txt") == "hello\nworld"
    assert extract_text(b"# Heading\ntext", ".md") == "# Heading\ntext"


def test_upload_storage_uses_opaque_filename(tmp_path):
    target = tmp_path / "opaque.txt"
    size = write_upload(io.BytesIO(b"safe content"), target)
    assert size == 12
    assert target.read_text() == "safe content"
    with pytest.raises(FileExistsError):
        write_upload(io.BytesIO(b"overwrite"), target)
