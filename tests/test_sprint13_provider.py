import pytest

from eiraos.application.providers.openai_adapter import _unpack_message
from eiraos.core.exceptions import EiraOSException


def test_unpack_message_returns_content():
    assert _unpack_message({"choices": [{"message": {"content": "hi"}}]}) == "hi"


def test_unpack_message_empty_string_on_missing_content():
    assert _unpack_message({"choices": [{"message": {}}]}) == ""


@pytest.mark.parametrize("bad", [
    None,
    "not json",
    {"choices": []},
    {"choices": "nope"},
    {"choices": [None]},
    {"choices": ["not a dict"]},
    {"choices": [{"message": None}]},
    {"choices": [{"message": 5}]},
])
def test_unpack_message_raises_sanitized_on_malformed(bad):
    with pytest.raises(EiraOSException) as ei:
        _unpack_message(bad)
    assert ei.value.status_code == 502
    # must not leak raw internals
    assert "traceback" not in str(ei.value.detail).lower()
