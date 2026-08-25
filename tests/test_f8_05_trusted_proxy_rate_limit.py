import pytest
from starlette.requests import Request

from eiraos.core.config import Settings, settings
from eiraos.core.ratelimit import client_identity, limiter


def request(peer: str, forwarded: str | None = None):
    headers = [] if forwarded is None else [(b"x-forwarded-for", forwarded.encode())]
    return Request({
        "type": "http", "method": "GET", "path": "/", "headers": headers,
        "query_string": b"", "client": (peer, 1234), "server": ("test", 80),
    })


def test_untrusted_peer_cannot_spoof_forwarded_identity(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    assert client_identity(request("203.0.113.9", "198.51.100.4")) == "203.0.113.9"


def test_trusted_proxy_chain_selects_nearest_untrusted_client(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "10.0.0.0/8,192.168.0.0/16")
    chain = "198.51.100.7, 192.168.2.3, 10.1.2.3"
    assert client_identity(request("10.2.3.4", chain)) == "198.51.100.7"


def test_malformed_forwarded_chain_falls_back_to_peer(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    assert client_identity(request("10.2.3.4", "198.51.100.7, attacker")) == "10.2.3.4"
    assert client_identity(request("10.2.3.4", ",".join(["198.51.100.7"] * 17))) == "10.2.3.4"
    assert client_identity(request("10.2.3.4", "1" * 1025)) == "10.2.3.4"


def test_ipv6_addresses_are_canonicalized(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "2001:db8:1::/48")
    assert client_identity(request("2001:db8:1::1", "2001:db8:2::9")) == "2001:db8:2::9"


def production(**overrides):
    values = dict(
        APP_ENV="production", SECRET_KEY="s" * 48, REDIS_URL="redis://redis:6379/0",
        USER_TOKEN_BUDGET_LIMIT=1000, ORGANIZATION_TOKEN_BUDGET_LIMIT=10000,
        CORS_ORIGINS="https://app.example.com", TRUSTED_HOSTS="api.example.com",
        TRUSTED_PROXY_CIDRS="10.20.0.0/16",
    )
    values.update(overrides)
    return Settings(**values)


def test_production_rejects_invalid_empty_and_global_proxy_trust():
    assert production().trusted_proxy_networks
    for value in ("", "not-a-network", "0.0.0.0/0", "::/0"):
        with pytest.raises(ValueError, match="proxy"):
            production(TRUSTED_PROXY_CIDRS=value)


def test_global_limiter_uses_trusted_proxy_identity_boundary():
    assert limiter._key_func is client_identity


def test_runtime_disables_uvicorn_implicit_proxy_rewrite():
    from pathlib import Path

    root = Path(__file__).parents[1]
    assert '"--no-proxy-headers"' in (root / "Dockerfile").read_text()
    assert "--no-proxy-headers" in (root / "docker-compose.yml").read_text()
    script = (root / "deploy/staging_deploy.sh").read_text()
    assert "TRUSTED_PROXY_CIDRS:?" in script
