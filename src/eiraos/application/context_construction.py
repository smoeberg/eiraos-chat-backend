"""F5-02 deterministic conversation context construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


class ContextBudgetExceeded(ValueError):
    """Mandatory prompt/system context cannot fit the selected model window."""


@dataclass(frozen=True, slots=True)
class ContextPolicy:
    context_window_tokens: int
    reserved_output_tokens: int = 1000
    max_history_tokens: int = 8000
    max_history_messages: int = 40
    chars_per_token: int = 4

    def __post_init__(self) -> None:
        if self.context_window_tokens <= 0 or self.chars_per_token <= 0:
            raise ValueError("context window and token ratio must be positive")
        if min(self.reserved_output_tokens, self.max_history_tokens, self.max_history_messages) < 0:
            raise ValueError("context policy limits cannot be negative")
        if self.reserved_output_tokens >= self.context_window_tokens:
            raise ValueError("output reservation must leave an input window")


@dataclass(frozen=True, slots=True)
class ConstructedContext:
    messages: tuple[dict[str, str], ...]
    system_prompt: str | None
    estimated_input_tokens: int
    history_tokens: int
    input_budget_tokens: int
    selected_history_ids: tuple[int, ...]
    truncated_history_count: int


class ConversationContextBuilder:
    """Select a bounded chronological history suffix plus the current prompt."""

    def __init__(self, policy: ContextPolicy):
        self._policy = policy

    def build(
        self,
        *,
        history_newest_first: Sequence[Any],
        current_prompt: str,
        system_prompt: str | None,
    ) -> ConstructedContext:
        prompt = self._content(current_prompt, required=True)
        system = self._content(system_prompt, required=False)
        input_budget = self._policy.context_window_tokens - self._policy.reserved_output_tokens
        mandatory_tokens = self._tokens(len(prompt)) + self._tokens(len(system or ""))
        if mandatory_tokens > input_budget:
            raise ContextBudgetExceeded("mandatory context exceeds the model input window")

        history_budget = min(
            self._policy.max_history_tokens,
            input_budget - mandatory_tokens,
        )
        eligible = []
        for item in history_newest_first[:self._policy.max_history_messages]:
            role = self._value(item, "role")
            content = self._content(self._value(item, "content"), required=False)
            status = self._value(item, "status", "completed")
            if role not in {"user", "assistant"} or status != "completed" or not content:
                continue
            eligible.append((item, role, content, self._tokens(len(content))))

        selected = []
        used = 0
        for item in eligible:
            size = item[3]
            if used + size > history_budget:
                break
            selected.append(item)
            used += size
        selected.reverse()
        while selected and selected[0][1] == "assistant":
            used -= selected.pop(0)[3]
        messages = tuple(
            [{"role": role, "content": content} for _, role, content, _ in selected]
            + [{"role": "user", "content": prompt}]
        )
        return ConstructedContext(
            messages=messages,
            system_prompt=system,
            estimated_input_tokens=mandatory_tokens + used,
            history_tokens=used,
            input_budget_tokens=input_budget,
            selected_history_ids=tuple(
                int(self._value(item, "id"))
                for item, _, _, _ in selected
                if self._value(item, "id") is not None
            ),
            truncated_history_count=len(eligible) - len(selected),
        )

    def _tokens(self, characters: int) -> int:
        return (characters + self._policy.chars_per_token - 1) // self._policy.chars_per_token

    @staticmethod
    def _value(item: Any, key: str, default=None):
        if isinstance(item, Mapping):
            return item.get(key, default)
        return getattr(item, key, default)

    @staticmethod
    def _content(value: Any, *, required: bool) -> str | None:
        if value is None and not required:
            return None
        if not isinstance(value, str):
            raise ContextBudgetExceeded("context content must be text")
        normalized = value.strip()
        if required and not normalized:
            raise ContextBudgetExceeded("current prompt cannot be empty")
        return normalized or None