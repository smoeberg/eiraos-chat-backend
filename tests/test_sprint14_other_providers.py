import pytest

from eiraos.application.providers.anthropic_adapter import _unpack_anthropic_message
from eiraos.application.providers.gemini_adapter import _unpack_gemini_text
from eiraos.core.exceptions import EiraOSException


def test_anthropic_happy_path():
    assert _unpack_anthropic_message({"content": [{"text": "hello"}]}) == "hello"


@pytest.mark.parametrize("bad", [
    None, "x", {}, {"content": []}, {"content": "nope"}, {"content": [None]}, {"content": [5]},
])
def test_anthropic_malformed_raises_sanitized(bad):
    with pytest.raises(EiraOSException) as ei:
        _unpack_anthropic_message(bad)
    assert ei.value.status_code == 502


def test_gemini_happy_path():
    assert _unpack_gemini_text({"candidates": [{"content": {"parts": [{"text": "hey"}]}}]}) == "hey"


@pytest.mark.parametrize("bad", [
    None, "x", {}, {"candidates": []}, {"candidates": "nope"},
    {"candidates": [None]}, {"candidates": [{"content": None}]},
    {"candidates": [{"content": {"parts": []}}]},
])
def test_gemini_malformed_raises_sanitized(bad):
    with pytest.raises(EiraOSException) as ei:
        _unpack_gemini_text(bad)
    assert ei.value.status_code == 502
