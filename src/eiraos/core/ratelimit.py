"""Central rate-limiter instance.

Owned here so both the app factory (main.py) and per-endpoint decorators
(auth/bots/chat) share the SAME Limiter instance without a circular import.

Defaults are intentionally conservative for auth endpoints to blunt
credential-stuffing / brute-force attacks.
"""
from slowapi import Limiter
from ipaddress import ip_address

from fastapi import Request
from eiraos.core.config import settings

MAX_FORWARDED_HEADER_CHARS = 1024
MAX_FORWARDED_HOPS = 16


def _address(value: str):
    try:
        return ip_address(value.strip())
    except ValueError:
        return None


def _trusted(address) -> bool:
    return address is not None and any(
        address.version == network.version and address in network
        for network in settings.trusted_proxy_networks
    )


def client_identity(request: Request) -> str:
    """Return peer IP unless an explicitly trusted proxy supplied a valid chain."""
    peer_text = request.client.host if request.client else "unknown"
    peer = _address(peer_text)
    if not _trusted(peer):
        return str(peer) if peer is not None else peer_text
    forwarded = request.headers.get("x-forwarded-for", "")
    if not forwarded:
        return str(peer)
    if len(forwarded) > MAX_FORWARDED_HEADER_CHARS:
        return str(peer)
    raw_chain = forwarded.split(",")
    if len(raw_chain) > MAX_FORWARDED_HOPS:
        return str(peer)
    chain = [_address(item) for item in raw_chain]
    if any(item is None for item in chain):
        return str(peer)
    for candidate in reversed(chain):
        if not _trusted(candidate):
            return str(candidate)
    return str(chain[0])

# Storage-backed via Redis when REDIS_URL is set; degrades to in-memory locally.
limiter = Limiter(
    key_func=client_identity,
    default_limits=["100/minute"],
    storage_uri=settings.REDIS_URL or None,
)

# Tight limits on identity endpoints.
AUTH_LOGIN_LIMIT = "5/minute"
AUTH_REGISTER_LIMIT = "5/minute"
AUTH_VERIFY_LIMIT = "5/minute"

# Creating a tenant has durable storage and authorization consequences. Keep
# this stricter than the global request limit while still allowing onboarding.
ORGANIZATION_CREATE_LIMIT = "5/minute"
