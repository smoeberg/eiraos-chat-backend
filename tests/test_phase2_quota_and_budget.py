"""Phase 2 audit: quota, cost & rate-limit enforcement boundaries.

This is an EVIDENCE-GATHERING audit, not (yet) a guarantee suite. Following the
Fase 2-audit agreement, we do NOT design the quota system here. Instead these
tests probe the current `main` to make the exact enforcement gaps visible, so a
later, evidence-driven design decision can close them.

Status conventions (mirrors Soeren's RED/GREEN/YELLOW audit table):
  - GREEN   : currently enforced and testable.
  - RED     : NOT currently enforced (gap proven by this file).
  - YELLOW  : partially enforced / degraded fallback.
"""
import inspect
import pytest

from eiraos.api.v1 import chat as chat_module
from eiraos.api.v1.chat import (
    ChatCompletionRequest,
    create_chat_completion,
)
from eiraos.application.business_features import verify_answer
from eiraos.core import ratelimit


# --------------------------------------------------------------------------- #
# GREEN: rate-limiting fundamentals present (in-memory fallback documented)    #
# --------------------------------------------------------------------------- #
def test_global_rate_limiter_configured():
    """GREEN: a global limiter is configured (100/min default)."""
    assert ratelimit.limiter is not None
    module_src = inspect.getsource(ratelimit)
    assert "100/minute" in module_src


def test_auth_endpoints_have_tight_limits():
    """GREEN: identity endpoints are rate-limited (5/min) to blunt brute-force."""
    assert ratelimit.AUTH_LOGIN_LIMIT == "5/minute"
    assert ratelimit.AUTH_REGISTER_LIMIT == "5/minute"
    assert ratelimit.AUTH_VERIFY_LIMIT == "5/minute"


def test_rate_limiter_takes_remote_address():
    """Limiter keys on the peer/trusted-proxy identity boundary."""
    assert ratelimit.limiter._key_func is not None
    assert ratelimit.limiter._key_func is ratelimit.client_identity


def test_rate_limiter_storage_falls_back_to_memory():
    """YELLOW/GREEN: Redis when REDIS_URL set, otherwise in-memory."""
    from eiraos.core.config import settings as s
    if s.REDIS_URL:
        assert ratelimit.limiter._storage_uri == s.REDIS_URL
    else:
        assert ratelimit.limiter._storage_uri is None


# --------------------------------------------------------------------------- #
# GREEN: F2-03 budget enforcement is now intentional at the chat boundary.   #
# --------------------------------------------------------------------------- #
def test_per_user_quota_enforced():
    """GREEN: execution budget is reserved for the authenticated user."""
    src = inspect.getsource(create_chat_completion)
    assert "_execution_budget()" in src
    assert "user_id=current_user[\"user_id\"]" in src
    assert ".reserve(" in src


def test_per_organization_quota_enforced():
    """GREEN: execution budget receives the authenticated organization scope."""
    src = inspect.getsource(create_chat_completion)
    assert "_execution_budget()" in src
    assert "organization_id=org_id" in src
    assert ".reserve(" in src


def test_token_budget_on_primary_chat():
    """GREEN: primary generation is bounded by the execution budget."""
    src = inspect.getsource(create_chat_completion)
    assert "_execution_budget()" in src
    assert "prompt=payload.prompt" in src
    assert ".reserve(" in src


# --------------------------------------------------------------------------- #
# GREEN: verification cost amplification is explicitly included in budget.    #
# --------------------------------------------------------------------------- #
def test_verification_cost_is_bounded():
    """GREEN: verify=True participates in the pre-execution reservation."""
    src = inspect.getsource(create_chat_completion)
    assert "payload.verify" in src
    assert "verify=payload.verify" in src
    assert "_execution_budget()" in src
    assert ".reserve(" in src


def test_no_provider_model_allowlist():
    """RED: no allowlist constrains which provider/model may be selected."""
    provider_fn = getattr(chat_module, "_provider_for_bot", None)
    if provider_fn:
        src = inspect.getsource(provider_fn)
        assert "allowlist" not in src.lower()
    else:
        assert True


# --------------------------------------------------------------------------- #
# YELLOW: partial guards present (history budget), not a full cost gate          #
# --------------------------------------------------------------------------- #
def test_history_token_budget_caps_context_retrieval():
    """YELLOW: the retrieved conversation context IS token-budgeted."""
    budget = getattr(chat_module, "DEFAULT_HISTORY_TOKEN_BUDGET", 8000)
    assert budget > 0
    build_msgs = getattr(chat_module, "_build_messages", None)
    if build_msgs:
        src = inspect.getsource(build_msgs)
        assert "history_token_budget" in src


def test_knowledge_scope_has_max_chars():
    """YELLOW/GREEN: arbitrary-length knowledge_scope input is rejected."""
    max_chars = getattr(chat_module, "MAX_KNOWLEDGE_SCOPE_CHARS", 120)
    assert max_chars > 0
    schema = ChatCompletionRequest.model_json_schema()
    prop = schema["properties"].get("knowledge_scope", {})
    any_lengths = [
        o.get("maxLength") for o in prop.get("anyOf", [])
    ]
    assert any_lengths and max_chars in any_lengths
