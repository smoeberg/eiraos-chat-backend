from types import SimpleNamespace
import inspect

import pytest

from eiraos.application.context_construction import (
    ContextBudgetExceeded,
    ContextPolicy,
    ConversationContextBuilder,
)
from eiraos.application.providers.capability_discovery import model_metadata


def _message(identity, role, content, status="completed"):
    return SimpleNamespace(id=identity, role=role, content=content, status=status)


def test_context_is_chronological_suffix_plus_current_prompt():
    history = [
        _message(4, "assistant", "dddd"),
        _message(3, "user", "cccc"),
        _message(2, "assistant", "bbbb"),
        _message(1, "user", "aaaa"),
    ]
    context = ConversationContextBuilder(ContextPolicy(
        context_window_tokens=10,
        reserved_output_tokens=2,
        max_history_tokens=2,
        chars_per_token=4,
    )).build(history_newest_first=history, current_prompt="now", system_prompt="rules")

    assert context.messages == (
        {"role": "user", "content": "cccc"},
        {"role": "assistant", "content": "dddd"},
        {"role": "user", "content": "now"},
    )
    assert context.selected_history_ids == (3, 4)
    assert context.truncated_history_count == 2
    assert context.system_prompt == "rules"
    assert all(message["role"] != "system" for message in context.messages)


def test_system_prompt_is_separate_and_counted_once():
    context = ConversationContextBuilder(ContextPolicy(
        context_window_tokens=10, reserved_output_tokens=2, chars_per_token=4,
    )).build(history_newest_first=[], current_prompt="1234", system_prompt="5678")
    assert context.estimated_input_tokens == 2
    assert context.messages == ({"role": "user", "content": "1234"},)
    assert context.system_prompt == "5678"


def test_identical_consecutive_user_prompt_is_never_deduplicated():
    context = ConversationContextBuilder(ContextPolicy(
        context_window_tokens=10, reserved_output_tokens=1, chars_per_token=4,
    )).build(
        history_newest_first=[_message(1, "user", "repeat")],
        current_prompt="repeat",
        system_prompt=None,
    )
    assert [message["content"] for message in context.messages] == ["repeat", "repeat"]


def test_only_completed_user_and_assistant_history_is_eligible():
    history = [
        _message(5, "assistant", "partial", "cancelled"),
        _message(4, "system", "old system"),
        _message(3, "assistant", "failed", "failed"),
        _message(2, "tool", "observation"),
        _message(1, "user", "valid"),
    ]
    context = ConversationContextBuilder(ContextPolicy(
        context_window_tokens=20, reserved_output_tokens=2, chars_per_token=4,
    )).build(history_newest_first=history, current_prompt="new", system_prompt=None)
    assert context.messages == (
        {"role": "user", "content": "valid"},
        {"role": "user", "content": "new"},
    )


def test_history_selection_never_splits_or_exceeds_budget():
    context = ConversationContextBuilder(ContextPolicy(
        context_window_tokens=6,
        reserved_output_tokens=1,
        max_history_tokens=2,
        chars_per_token=4,
    )).build(
        history_newest_first=[_message(2, "assistant", "x" * 12), _message(1, "user", "ok")],
        current_prompt="now",
        system_prompt=None,
    )
    assert context.messages == ({"role": "user", "content": "now"},)
    assert context.history_tokens == 0
    assert context.truncated_history_count == 2


def test_budget_never_emits_an_orphan_assistant_turn():
    context = ConversationContextBuilder(ContextPolicy(
        context_window_tokens=5,
        reserved_output_tokens=1,
        max_history_tokens=1,
        chars_per_token=4,
    )).build(
        history_newest_first=[_message(2, "assistant", "reply"), _message(1, "user", "question")],
        current_prompt="new",
        system_prompt=None,
    )
    assert context.messages == ({"role": "user", "content": "new"},)
    assert context.history_tokens == 0


def test_mandatory_context_overflow_fails_before_provider_request():
    builder = ConversationContextBuilder(ContextPolicy(
        context_window_tokens=3, reserved_output_tokens=1, chars_per_token=1,
    ))
    with pytest.raises(ContextBudgetExceeded, match="mandatory context"):
        builder.build(history_newest_first=[], current_prompt="abc", system_prompt=None)


def test_policy_rejects_invalid_windows():
    with pytest.raises(ValueError):
        ContextPolicy(context_window_tokens=100, reserved_output_tokens=100)
    with pytest.raises(ValueError):
        ContextPolicy(context_window_tokens=100, max_history_tokens=-1)


def test_model_window_comes_from_governed_f4_catalog():
    assert model_metadata("gemini", "gemini-1.5-pro").context_window_tokens == 2_000_000
    with pytest.raises(ValueError, match="unavailable"):
        model_metadata("openai", "unknown")


def test_chat_preparation_uses_context_boundary_and_separate_system_prompt():
    from eiraos.api.v1.chat import create_chat_completion

    source = inspect.getsource(create_chat_completion)
    assert "ConversationContextBuilder" in source
    assert "model_metadata" in source
    assert "context.system_prompt" in source
    assert "Message.status == \"completed\"" in source
    assert "Message.execution_id != persisted_execution.execution_id" in source