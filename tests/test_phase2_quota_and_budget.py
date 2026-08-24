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

from eiraos.api.v1.chat import (
    ChatCompletionRequest,
    create_chat_completion,
    _build_messages,
    DEFAULT_HISTORY_TOKEN_BUDGET,
    MAX_KNOWLEDGE_SCOPE_CHARS,
    _find_verifier_bot,
    _provider_for_bot,
)
from eiraos.application.business_features import verify_answer
from eiraos.core import ratelimit


# --------------------------------------------------------------------------- #
# GREEN: rate-limiting fundamentals present (in-memory fallback documented)    #
# --------------------------------------------------------------------------- #
def test_global_rate_limiter_configured():
    """GREEN: a global limiter is configured (100/min default)."""
    assert ratelimit.limiter is not None
    # The limiter is constructed in this module with a 100/minute default.
    module_src = inspect.getsource(ratelimit)
    assert "100/minute" in module_src


def test_auth_endpoints_have_tight_limits():
    """GREEN: identity endpoints are rate-limited (5/min) to blunt brute-force."""
    assert ratelimit.AUTH_LOGIN_LIMIT == "5/minute"
    assert ratelimit.AUTH_REGISTER_LIMIT == "5/minute"
    assert ratelimit.AUTH_VERIFY_LIMIT == "5/minute"


def test_rate_limiter_takes_remote_address():
    """GREEN/YELLOW: limiter keys on remote address.

    Documented as YELLOW rather than GREEN because IP is not equivalent to an
    authenticated principal on a multi-tenant platform — the Fase 2 audit notes
    that IP-only limiting can be inconsistent (shared NAT, forwarding proxies).
    """
    assert ratelimit.limiter._key_func is not None
    assert ratelimit.limiter._key_func.__module__ == "slowapi.util"


def test_rate_limiter_storage_falls_back_to_memory():
    """YELLOW/GREEN: Redis when REDIS_URL set, otherwise in-memory.

    In-memory fallback is correct for single-process/dev, but means horizontal
    scaling needs REDIS_URL configured for the limits to be shared fleet-wide.
    """
    from eiraos.core.config import settings as s
    if s.REDIS_URL:
        assert ratelimit.limiter._storage_uri == s.REDIS_URL
    else:
        assert ratelimit.limiter._storage_uri is None


# --------------------------------------------------------------------------- #
# RED: per-user / per-org quota & cost budgets are NOT enforced                 #
# --------------------------------------------------------------------------- #
def test_no_per_user_quota_enforced():
    """RED: chat completion handler has no per-user quota gate."""
    src = inspect.getsource(create_chat_completion)
    # No quota lookup / counter for the calling user before serving.
    assert "quota" not in src.lower()
    assert "budget" not in src.lower()


def test_no_per_organization_quota_enforced():
    """RED: chat completion handler has no per-organization budget gate."""
    src = inspect.getsource(create_chat_completion)
    assert "organization" not in src or "quota" not in src.lower()


def test_no_token_budget_on_primary_chat():
    """RED: no token/cost budget is enforced on primary generation.

    NOTE: history is capped via DEFAULT_HISTORY_TOKEN_BUDGET, but that caps the
    *retrieved conversation context*, it does NOT constrain the cost of the
    generated output itself.
    """
    src = inspect.getsource(create_chat_completion)
    assert "budget" not in src.lower()


# --------------------------------------------------------------------------- #
# RED: structured-extraction / verification cost amplification unconstrained    #
# --------------------------------------------------------------------------- #
def test_verification_runs_unbounded_extra_cost():
    """RED: `verify=True` triggers a second full provider call with no cost guard.

    The verifier invocation is a genuine cost amplifier (potentially a more
    expensive/separate model) and is currently unlimited by any per-call or
    per-user budget.
    """
    src = inspect.getsource(create_chat_completion)
    # verify path exists...
    assert "payload.verify" in src
    # ...but nothing bounds its additional spend.
    assert "budget" not in src.lower()


def test_no_provider_model_allowlist():
    """RED: no allowlist constrains which provider/model may be selected.

    The provider is looked up from the stored Bot config; there is no
    central allowlist / allowlist-gate at call time, so a bot configured with a
    costly model is served regardless of budget.
    """
    src = inspect.getsource(_provider_for_bot)
    assert "allowlist" not in src.lower()


# --------------------------------------------------------------------------- #
# YELLOW: partial guards present (history budget), not a full cost gate          #
# --------------------------------------------------------------------------- #
def test_history_token_budget_caps_context_retrieval():
    """YELLOW: the retrieved conversation context IS token-budgeted.

    This constrains input context cost (retrieval), but is NOT a full
    generation cost / quota gate.
    """
    assert DEFAULT_HISTORY_TOKEN_BUDGET > 0
    src = inspect.getsource(_build_messages)
    assert "history_token_budget" in src
    assert "DEFAULT_HISTORY_TOKEN_BUDGET" in src


def test_knowledge_scope_has_max_chars():
    """YELLOW/GREEN: arbitrary-length knowledge_scope input is rejected.

    Limits input size, but is not a cost/quota control.
    """
    assert MAX_KNOWLEDGE_SCOPE_CHARS > 0
    schema = ChatCompletionRequest.model_json_schema()
    prop = schema["properties"]["knowledge_scope"]
    # knowledge_scope is `str | None`, so max_length sits on the string variant.
    any_lengths = [
        o.get("maxLength") for o in prop.get("anyOf", [])
    ]
    assert any_lengths and MAX_KNOWLEDGE_SCOPE_CHARS in any_lengths
