"""F5-02 deterministic conversation context construction."""

from __future__ import annotations

import hashlib
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
    max_source_messages: int = 200
    max_compaction_tokens: int = 0
    chars_per_token: int = 4

    def __post_init__(self) -> None:
        if self.context_window_tokens <= 0 or self.chars_per_token <= 0:
            raise ValueError("context window and token ratio must be positive")
        if min(
            self.reserved_output_tokens,
            self.max_history_tokens,
            self.max_history_messages,
            self.max_compaction_tokens,
        ) < 0:
            raise ValueError("context policy limits cannot be negative")
        if self.max_source_messages < self.max_history_messages:
            raise ValueError("source window cannot be smaller than the raw history window")
        if self.max_source_messages <= 0:
            raise ValueError("source window must be positive")
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
    compaction_source_ids: tuple[int, ...] = ()
    compaction_digest: str | None = None


@dataclass(frozen=True, slots=True)
class CompactionArtifact:
    content: str
    source_ids: tuple[int, ...]
    source_digest: str
    estimated_tokens: int


class DeterministicContextCompactor:
    """Create a bounded, attributable extract from older conversation history."""

    _PREFIX = "<conversation_compaction untrusted=\"true\">\n"
    _SUFFIX = "\n</conversation_compaction>"

    def compact(
        self,
        *,
        history_chronological: Sequence[Any],
        token_budget: int,
        chars_per_token: int,
    ) -> CompactionArtifact | None:
        if not history_chronological or token_budget <= 0 or chars_per_token <= 0:
            return None
        canonical: list[str] = []
        source_ids: list[int] = []
        for item in history_chronological:
            role = ConversationContextBuilder._value(item, "role")
            content = ConversationContextBuilder._content(
                ConversationContextBuilder._value(item, "content"), required=False,
            )
            if role not in {"user", "assistant"} or not content:
                continue
            identity = ConversationContextBuilder._value(item, "id")
            if identity is not None:
                source_ids.append(int(identity))
            canonical.append(f"[{role}] {content}")
        if not canonical:
            return None
        digest = hashlib.sha256("\n".join(canonical).encode("utf-8")).hexdigest()
        header = self._PREFIX + f"source_sha256={digest}\n"
        capacity = token_budget * chars_per_token
        payload_capacity = capacity - len(header) - len(self._SUFFIX)
        if payload_capacity <= 0:
            return None
        payload = "\n".join(canonical)
        if len(payload) > payload_capacity:
            marker = "\n[older context truncated]"
            if payload_capacity <= len(marker):
                return None
            payload = payload[: payload_capacity - len(marker)].rstrip() + marker
        content = header + payload + self._SUFFIX
        return CompactionArtifact(
            content=content,
            source_ids=tuple(source_ids),
            source_digest=digest,
            estimated_tokens=(len(content) + chars_per_token - 1) // chars_per_token,
        )


class ConversationContextBuilder:
    """Select a bounded chronological history suffix plus the current prompt."""

    def __init__(
        self,
        policy: ContextPolicy,
        compactor: DeterministicContextCompactor | None = None,
    ):
        self._policy = policy
        self._compactor = compactor or DeterministicContextCompactor()

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
        for item in history_newest_first[:self._policy.max_source_messages]:
            role = self._value(item, "role")
            content = self._content(self._value(item, "content"), required=False)
            status = self._value(item, "status", "completed")
            if role not in {"user", "assistant"} or status != "completed" or not content:
                continue
            eligible.append((item, role, content, self._tokens(len(content))))

        selected, used = self._select(eligible, history_budget)
        fallback_selected, fallback_used = selected, used
        omitted = eligible[len(selected):]
        artifact = None
        if omitted and self._policy.max_compaction_tokens:
            raw_budget = max(0, history_budget - self._policy.max_compaction_tokens)
            selected, used = self._select(eligible, raw_budget)
            omitted = eligible[len(selected):]
            artifact = self._compactor.compact(
                history_chronological=[item for item, _, _, _ in reversed(omitted)],
                token_budget=min(
                    self._policy.max_compaction_tokens,
                    history_budget - used,
                ),
                chars_per_token=self._policy.chars_per_token,
            )
            if artifact is None:
                selected, used = fallback_selected, fallback_used
        selected.reverse()
        while selected and selected[0][1] == "assistant":
            used -= selected.pop(0)[3]
        prefix = []
        if artifact is not None:
            prefix.append({"role": "user", "content": artifact.content})
        messages = tuple(
            prefix
            + [{"role": role, "content": content} for _, role, content, _ in selected]
            + [{"role": "user", "content": prompt}]
        )
        compaction_tokens = artifact.estimated_tokens if artifact else 0
        return ConstructedContext(
            messages=messages,
            system_prompt=system,
            estimated_input_tokens=mandatory_tokens + used + compaction_tokens,
            history_tokens=used + compaction_tokens,
            input_budget_tokens=input_budget,
            selected_history_ids=tuple(
                int(self._value(item, "id"))
                for item, _, _, _ in selected
                if self._value(item, "id") is not None
            ),
            truncated_history_count=len(eligible) - len(selected),
            compaction_source_ids=artifact.source_ids if artifact else (),
            compaction_digest=artifact.source_digest if artifact else None,
        )

    def _select(self, eligible, budget):
        selected = []
        used = 0
        for item in eligible[:self._policy.max_history_messages]:
            size = item[3]
            if used + size > budget:
                break
            selected.append(item)
            used += size
        return selected, used

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