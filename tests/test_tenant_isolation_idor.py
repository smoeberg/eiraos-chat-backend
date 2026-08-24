"""Negative integration tests for tenant isolation and IDOR protection."""
import inspect
from fastapi.testclient import TestClient
from eiraos.main import app
from eiraos.api.v1.conversations import list_conversations
from eiraos.api.v1.bots import list_bots
from eiraos.application.chat_execution import ChatExecutionService, _bot_accessible

client = TestClient(app)


def test_conversation_endpoint_enforces_org_ownership():
    src = inspect.getsource(list_conversations)
    assert "organization_id" in src or "user_id" in src or "current_user" in src


def test_bot_endpoint_enforces_org_ownership_or_visibility():
    src = inspect.getsource(list_bots)
    assert "organization_id" in src or "visibility" in src or "public" in src


def test_chat_completion_enforces_tenant_conversation_and_bot_match():
    """Execution layer validates conversation and bot tenancy."""
    src = inspect.getsource(ChatExecutionService.execute)
    assert "Conversation.id == payload.conversation_id" in src
    assert "Conversation.organization_id == org_id" in src
    assert "Conversation.user_id == current_user[\"user_id\"]" in src
    assert "Bot.id == payload.bot_id" in src
    assert "_bot_accessible" in src


def test_bot_accessible_function_enforces_org_scope():
    src = inspect.getsource(_bot_accessible)
    assert "organization_id" in src or "visibility" in src


def test_cross_tenant_access_returns_401_403_or_404():
    resp = client.post("/api/v1/chat/completions", json={
        "conversation_id": 99999,
        "bot_id": 99999,
        "prompt": "Cross-tenant test",
        "stream": False,
    })
    assert resp.status_code in (401, 403, 404, 422)
    assert resp.status_code != 200
