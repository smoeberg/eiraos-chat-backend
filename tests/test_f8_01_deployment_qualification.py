from pathlib import Path

from eiraos.core.config import Settings


ROOT = Path(__file__).parents[1]


def read(path):
    return (ROOT / path).read_text()


def test_release_image_contains_migration_runtime():
    dockerfile = read("Dockerfile")
    assert "COPY alembic.ini ./alembic.ini" in dockerfile
    assert "COPY alembic/ ./alembic/" in dockerfile
    assert "USER 10001" in dockerfile


def test_release_image_installs_package_from_source_before_runtime_stage():
    dockerfile = read("Dockerfile")
    builder, runtime = dockerfile.split("FROM python:3.11-slim", maxsplit=2)[1:]

    assert "COPY pyproject.toml README.md ./" in builder
    assert "COPY src/ ./src/" in builder
    assert builder.index("COPY src/ ./src/") < builder.index("RUN pip install")
    assert "COPY src/ ./src/" not in runtime
    assert "PYTHONPATH" not in runtime


def test_env_example_documents_complete_production_contract():
    values = {}
    for raw_line in read(".env.example").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value

    required = {
        "APP_ENV", "RELEASE_SHA", "DATABASE_URL", "SECRET_KEY", "REDIS_URL",
        "CORS_ORIGINS", "TRUSTED_HOSTS", "TRUSTED_PROXY_CIDRS",
        "ALLOW_PUBLIC_REGISTER", "USER_TOKEN_BUDGET_LIMIT",
        "ORGANIZATION_TOKEN_BUDGET_LIMIT",
    }
    assert required <= values.keys()
    assert values["APP_ENV"] == "production"
    assert values["REDIS_URL"].startswith(("redis://", "rediss://"))
    assert values["CORS_ORIGINS"].startswith("https://")
    assert values["TRUSTED_PROXY_CIDRS"] == "replace-with-ingress-proxy-cidr"
    assert values["SECRET_KEY"] == "change-me"
    assert values["ALLOW_PUBLIC_REGISTER"] == "false"


def test_compose_uses_validated_production_settings_for_api_and_worker():
    compose = read("docker-compose.yml")
    assert compose.count("APP_ENV: production") == 2
    assert compose.count("REDIS_URL: redis://redis:6379/0") == 2
    assert sum(
        line.strip().startswith("USER_TOKEN_BUDGET_LIMIT:")
        for line in compose.splitlines()
    ) == 2
    assert sum(
        line.strip().startswith("ORGANIZATION_TOKEN_BUDGET_LIMIT:")
        for line in compose.splitlines()
    ) == 2
    assert compose.count("RELEASE_SHA: ${RELEASE_SHA:?RELEASE_SHA must be set}") == 2
    assert compose.count('ALLOW_PUBLIC_REGISTER: "false"') == 2
    assert "REDIS_HOST" not in compose and "REDIS_PORT" not in compose
    assert sum(line.strip().startswith("CORS_ORIGINS:") for line in compose.splitlines()) == 2
    assert sum(line.strip().startswith("TRUSTED_HOSTS:") for line in compose.splitlines()) == 2


def test_kubernetes_api_and_worker_fail_closed_on_required_redis():
    api = read("deploy/k8s/deployment.yaml")
    worker = read("deploy/k8s/worker.yaml")
    for manifest in (api, worker):
        assert "APP_ENV" in manifest and 'value: "production"' in manifest
        assert "USER_TOKEN_BUDGET_LIMIT" in manifest
        assert "ORGANIZATION_TOKEN_BUDGET_LIMIT" in manifest
        assert "CORS_ORIGINS" in manifest and "TRUSTED_HOSTS" in manifest
        assert 'name: ALLOW_PUBLIC_REGISTER\n          value: "false"' in manifest
        assert "key: redis-url" in manifest
        redis_block = manifest[manifest.index("key: redis-url"):]
        assert not redis_block.lstrip().startswith("key: redis-url\n              optional: true")
        assert "allowPrivilegeEscalation: false" in manifest
        assert "readOnlyRootFilesystem: true" in manifest
        assert "namespace:" not in manifest


def test_staging_secret_contract_matches_manifests_and_updates_worker():
    script = read("deploy/staging_deploy.sh")
    for key in (
        "jwt-secret-key", "database-url", "redis-url", "openai-api-key",
        "user-token-budget-limit", "organization-token-budget-limit",
    ):
        assert f"--from-literal={key}=" in script
    assert "apply -f deploy/k8s/worker.yaml" in script
    assert "apply -f deploy/k8s/worker-networkpolicy.yaml" in script
    assert "set image deployment/eiraos-worker" in script
    assert 'SVC_NAME="${SVC_NAME:-eiraos-chat-backend-svc}"' in script
    assert "rollout status deployment/eiraos-worker" in script
    assert '\\"name\\": \\"DATABASE_URL\\"' in script
    assert '\\"key\\": \\"database-url\\"' in script
    assert '\\"envFrom\\"' not in script


def test_production_can_boot_without_unused_platform_provider_key():
    config = Settings(
        APP_ENV="production", SECRET_KEY="s" * 48,
        OPENAI_API_KEY=None, REDIS_URL="redis://redis:6379/0",
        USER_TOKEN_BUDGET_LIMIT=1000, ORGANIZATION_TOKEN_BUDGET_LIMIT=10000,
        CORS_ORIGINS="https://app.example.com",
        TRUSTED_HOSTS="api.example.com",
    )
    assert config.OPENAI_API_KEY is None


def test_worker_network_policy_denies_ingress_and_bounds_egress():
    policy = read("deploy/k8s/worker-networkpolicy.yaml")
    assert "app: eiraos-worker" in policy
    assert "ingress: []" in policy
    for port in (53, 443, 5432, 6379):
        assert f"port: {port}" in policy


def test_blank_optional_provider_key_is_normalized_to_absent():
    config = Settings(
        APP_ENV="production", SECRET_KEY="s" * 48,
        OPENAI_API_KEY="", REDIS_URL="redis://redis:6379/0",
        USER_TOKEN_BUDGET_LIMIT=1000, ORGANIZATION_TOKEN_BUDGET_LIMIT=10000,
        CORS_ORIGINS="https://app.example.com",
        TRUSTED_HOSTS="api.example.com",
    )
    assert config.OPENAI_API_KEY is None
