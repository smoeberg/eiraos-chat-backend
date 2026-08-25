import pytest

from eiraos.workers.redis_config import redis_settings_from_url


def test_plain_redis_dsn_preserves_identity_without_tls():
    settings = redis_settings_from_url("redis://queue-user:secret@redis.internal:6380/7")
    assert settings.host == "redis.internal"
    assert settings.port == 6380
    assert settings.database == 7
    assert settings.username == "queue-user"
    assert settings.password == "secret"
    assert settings.ssl is False


def test_rediss_dsn_enables_tls_and_hostname_verification():
    settings = redis_settings_from_url("rediss://queue-user:secret@redis.example.com:6380/4")
    assert settings.host == "redis.example.com"
    assert settings.port == 6380
    assert settings.database == 4
    assert settings.username == "queue-user"
    assert settings.password == "secret"
    assert settings.ssl is True
    assert settings.ssl_cert_reqs == "required"
    assert settings.ssl_check_hostname is True


def test_invalid_redis_dsn_fails_closed():
    with pytest.raises(RuntimeError, match="invalid DSN scheme"):
        redis_settings_from_url("http://redis.example.com:6379/0")
