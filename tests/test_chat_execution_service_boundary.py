"""Architecture tests for the extracted chat execution boundary."""

from pathlib import Path


CHAT = Path(__file__).parents[1] / "src/eiraos/api/v1/chat.py"


def test_chat_controller_is_thin_and_delegates_execution():
    source = CHAT.read_text(encoding="utf-8")
    assert "ChatExecutionService" in source
    assert "chat_execution_service.execute" in source
    assert "generate_chat_completion" not in source
    assert "stream_chat_completion" not in source
    assert "verify_answer" not in source
    assert "SecretService.resolve" not in source
    assert "RAGService.hybrid_search" not in source
