"""Sprint 8: the app's active logger must include the PII redaction processor."""
import structlog
import eiraos.main as m  # triggers setup_logging() on import


def test_active_structlog_chain_includes_redact_pii():
    """The running structlog processor chain must scrub secrets (fail-closed)."""
    cfg = structlog.get_config()
    processors = cfg["processors"]
    names = {getattr(p, "__name__", str(p)) for p in processors}
    # redact_pii must be present in the globally-active chain.
    assert "redact_pii" in names, f"redaction processor missing from active chain: {names}"


def test_redact_pii_is_exported_and_runs():
    from eiraos.core.logging import redact_pii, REDACTED_VALUE
    out = redact_pii(None, "debug", {"secret": "sk-abc", "ok": 1})
    assert out["secret"] == REDACTED_VALUE
    assert out["ok"] == 1


def test_main_uses_setup_logging():
    import inspect
    import eiraos.main as m
    src = inspect.getsource(m)
    # The real app must bootstrap via setup_logging (which enables redaction),
    # not re-configure structlog without redaction.
    assert "setup_logging()" in src
    # guard: the old non-redacting inline structlog.configure should be gone
    assert 'structlog.processors.JSONRenderer()]' not in src.replace("    ", "")
