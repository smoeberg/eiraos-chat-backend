import inspect

from eiraos.api.v1.conversations import get_conversation_messages, list_conversations


def test_messages_endpoint_is_paginated():
    """Messages list must expose limit/offset (not an unbounded .all())."""
    params = inspect.signature(get_conversation_messages).parameters
    assert "limit" in params and "offset" in params


def test_conversations_list_is_paginated():
    params = inspect.signature(list_conversations).parameters
    assert "limit" in params and "offset" in params


def test_list_endpoint_source_bounds_result_sets():
    """Source reflects .limit() so listings cannot grow unboundedly."""
    from eiraos.api.v1.conversations import get_conversation_messages
    src = inspect.getsource(get_conversation_messages)
    assert ".limit(" in src and ".offset(" in src
