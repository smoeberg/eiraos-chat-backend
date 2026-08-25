from pathlib import Path

from eiraos.api.v1.auth import UserRegister
from eiraos.core.config import Settings


ROOT = Path(__file__).parents[1]


def test_security_ci_audits_installed_dependency_graph():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "python -m pip_audit" in workflow
    assert workflow.index("pip install -e") < workflow.index("python -m pip_audit")


def test_dependency_updates_cover_runtime_and_delivery_surfaces():
    config = (ROOT / ".github/dependabot.yml").read_text()
    assert "package-ecosystem: pip" in config
    assert "package-ecosystem: github-actions" in config
    assert "package-ecosystem: docker" in config


def test_production_gate_rejects_open_ingress_and_weak_session_config():
    base = dict(
        APP_ENV="production", SECRET_KEY="s" * 48,
        OPENAI_API_KEY="sk-real-production-key",
        REDIS_URL="redis://redis:6379/0",
        CORS_ORIGINS="https://app.example.com",
        TRUSTED_HOSTS="api.example.com",
    )
    assert Settings(**base)
    for override in (
        {"TRUSTED_HOSTS": "*"}, {"CORS_ORIGINS": "http://localhost:3000"},
        {"REDIS_URL": ""}, {"ALGORITHM": "none"},
    ):
        values = base | override
        try:
            Settings(**values)
        except ValueError:
            continue
        raise AssertionError(f"production accepted unsafe settings: {override}")


def test_identity_gate_retains_password_policy():
    assert UserRegister.model_fields["password"].metadata
