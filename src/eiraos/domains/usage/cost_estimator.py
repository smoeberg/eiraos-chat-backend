"""Deterministic pre-execution cost estimation for F2-02."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostEstimate:
    primary_tokens: int
    verifier_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.primary_tokens + self.verifier_tokens


class CostEstimator:
    def __init__(self, *, input_chars_per_token: int = 4, output_tokens: int = 1024) -> None:
        if input_chars_per_token <= 0 or output_tokens < 0:
            raise ValueError("invalid cost estimator configuration")
        self.input_chars_per_token = input_chars_per_token
        self.output_tokens = output_tokens

    def estimate(self, *, prompt: str, verify: bool) -> CostEstimate:
        if not isinstance(prompt, str):
            raise TypeError("prompt must be a string")
        input_tokens = (len(prompt) + self.input_chars_per_token - 1) // self.input_chars_per_token
        primary = input_tokens + self.output_tokens
        verifier = primary if verify else 0
        return CostEstimate(primary_tokens=primary, verifier_tokens=verifier)
