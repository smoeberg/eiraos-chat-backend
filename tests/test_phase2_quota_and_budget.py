"""Phase 2 audit: quota, cost & rate-limit enforcement boundaries."""
import inspect

from eiraos.application.chat_execution import (
    ChatCompletionRequest,
    ChatExecutionService,
    _build_messages,
    DEFAULT_HISTORY_TOKEN_BUDGET,
    MAX_KNOWLEDGE_SCOPE_CHARS,
    _provider_for_bot,
)
from eiraos.core import ratelimit


def test_global_rate_limiter_configured():
    assert ratelimit.limiter is not None
    assert "100/minute" in inspect.getsource(ratelimit)


def test_auth_endpoints_have_tight_limits():
    assert ratelimit.AUTH_LOGIN_LIMIT == "5/minute"
    assert ratelimit.AUTH_REGISTER_LIMIT == "5/minute"
    assert ratelimit.AUTH_VERIFY_LIMIT == "5/minute"


def test_rate_limiter_takes_remote_address():
    assert ratelimit.limiter._key_func is not None
    assert ratelimit.limiter._key_func.__module__ == "slowapi.util"


def test_rate_limiter_storage_falls_back_to_memory():
    from eiraos.core.config import settings as s
    if s.REDIS_URL:
        assert ratelimit.limiter._storage_uri == s.REDIS_URL
    else:
        assert ratelimit.limiter._storage_uri is None


def test_no_per_user_quota_enforced():
    src = inspect.getsource(ChatExecutionService.execute)
    assert "quota" not in src.lower()
    assert "budget" not in src.lower()


def test_no_per_organization_quota_enforced():
    src = inspect.getsource(ChatExecutionService.execute)
    assert "quota" not in src.lower()


def test_no_token_budget_on_primary_chat():
    src = inspect.getsource(ChatExecutionService._execute_non_streaming)
    assert "budget" not in src.lower()


def test_verification_runs_unbounded_extra_cost():
    src = inspect.getsource(ChatExecutionService._execute_non_streaming)
    assert "payload.verify" in src
    assert "budget" not in src.lower()


def test_no_provider_model_allowlist():
    src = inspect.getsource(_provider_for_bot)
    assert "allowlist" not in src.lower()


def test_history_token_budget_caps_context_retrieval():
    assert DEFAULT_HISTORY_TOKEN_BUDGET > 0
    src = inspect.getsource(_build_messages)
    assert "history_token_budget" in src
    assert "DEFAULT_HISTORY_TOKEN_BUDGET" in src


def test_knowledge_scope_has_max_chars():
    assert MAX_KNOWLEDGE_SCOPE_CHARS > 0
    schema = ChatCompletionRequest.model_json_schema()
    prop = schema["properties"]["knowledge_scope"]
    any_lengths = [o.get("maxLength") for o in prop.get("anyOf", [])]
    assert any_lengths and MAX_KNOWLEDGE_SCOPE_CHARS in any_lengths
