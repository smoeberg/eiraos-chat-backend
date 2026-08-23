"""Central rate-limiter instance.

Owned here so both the app factory (main.py) and per-endpoint decorators
(auth/bots/chat) share the SAME Limiter instance without a circular import.

Defaults are intentionally conservative for auth endpoints to blunt
credential-stuffing / brute-force attacks.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from eiraos.core.config import settings

# Storage-backed via Redis when REDIS_URL is set; degrades to in-memory locally.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute"],
    storage_uri=settings.REDIS_URL,
)

# Tight limits on identity endpoints.
AUTH_LOGIN_LIMIT = "5/minute"
AUTH_REGISTER_LIMIT = "5/minute"
AUTH_VERIFY_LIMIT = "5/minute"
