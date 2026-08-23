import sys
import structlog

# Substrings (normalized: lowercased, punctuation stripped) whose values must
# never appear verbatim in logs. Covers authorization, api_key, api-key,
# api-key, password, pwd, secret, token, jwt, email, cookie, session, credit
# card numbers, IBAN, etc.
SENSITIVE_KEYS = (
    "authorization", "auth", "apikey", "api", "password", "pwd",
    "secret", "token", "jwt", "email", "cookie", "session",
    "creditcard", "ccnumber", "iban", "phonenumber",
)

REDACTED_VALUE = "[REDACTED]"


def _key_matches(key: str) -> bool:
    """Decision on whether a dict key is sensitive (normalized match)."""
    norm = key.lower().replace("_", "").replace("-", "").replace(" ", "")
    return any(p in norm for p in SENSITIVE_KEYS)


def _redact_one(key, value):
    """Redact a single key/value pair (recursing into containers)."""
    if isinstance(value, dict):
        return _walk(value)
    if isinstance(value, (list, tuple)):
        return [_redact_one(key, v) for v in value]
    if isinstance(value, str) and _key_matches(key):
        # Mask the value AND strip common inline prefixes like "Bearer ".
        return REDACTED_VALUE
    return value


def _walk(node):
    if isinstance(node, dict):
        return {k: _redact_one(k, v) for k, v in node.items()}
    if isinstance(node, (list, tuple)):
        return [_walk(v) for v in node]
    return node


def redact_pii(_logger, _method_name, event_dict):
    """structlog processor that recursively masks sensitive field values."""
    return _walk(event_dict)


def setup_logging():
    """Configure structured JSON logging using structlog with PII redaction."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            redact_pii,                                       # security: scrub PII/secrets
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO level
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )
