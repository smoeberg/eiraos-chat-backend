from eiraos.application.providers.policy import authorize_provider_model


def test_provider_aliases_normalize_to_canonical_names():
    assert authorize_provider_model("claude", "claude-3-5-sonnet-20241022") == ("anthropic", "claude-3-5-sonnet-20241022")
    assert authorize_provider_model("gemini", "gemini-1.5-pro") == ("google", "gemini-1.5-pro")
