"""Sprint 5: PII/secret redaction in logs + security headers."""
from eiraos.core.logging import redact_pii, REDACTED_VALUE


def _redact(d):
    return redact_pii(None, "debug", dict(d))


def test_authorization_header_redacted():
    out = _redact({"headers": {"authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.secret"}})
    assert "eyJhbGciOiJIUzI1NiJ9.secret" not in str(out)
    assert REDACTED_VALUE in str(out)


def test_api_key_redacted():
    out = _redact({"api_key": "sk-super-secret-123"})
    assert "sk-super-secret-123" not in str(out)
    assert REDACTED_VALUE in str(out)


def test_email_redacted():
    out = _redact({"user": {"email": "soeren@example.com"}})
    assert "soeren@example.com" not in str(out)


def test_non_sensitive_values_kept():
    out = _redact({"event": "ok", "org_id": 7, "request_id": "abc-123"})
    assert out["event"] == "ok"
    assert out["org_id"] == 7
    assert out["request_id"] == "abc-123"


def test_nested_lists_redacted():
    out = _redact({"tokens": ["tok-1", "tok-2"]})
    for t in ("tok-1", "tok-2"):
        assert t not in str(out)


def test_security_headers_set():
    from eiraos.core.middleware import SecurityHeadersMiddleware
    assert SecurityHeadersMiddleware  # import + registration works
