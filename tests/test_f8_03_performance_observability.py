import argparse

import httpx
import pytest

from scripts.f8_performance_gate import Sample, percentile, run_scenario, summarize


def test_percentile_and_error_summary_are_deterministic():
    samples = [Sample(200, value, value != 40) for value in (10, 20, 30, 40, 50)]
    assert percentile([10, 20, 30, 40, 50], 0.95) == 50
    assert summarize(samples) == {
        "requests": 5, "errors": 1, "error_rate": 0.2,
        "p50_ms": 30, "p95_ms": 50, "max_ms": 50,
    }


@pytest.mark.asyncio
async def test_scenario_counts_status_mismatch_without_hiding_latency():
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(200 if calls < 3 else 503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://test") as client:
        report = await run_scenario(client, "/health/live", 200, requests=4, concurrency=1)
    assert report["requests"] == 4
    assert report["errors"] == 2
    assert report["error_rate"] == 0.5
    assert report["p95_ms"] >= 0


@pytest.mark.asyncio
async def test_health_and_deployment_expose_same_release_contract(monkeypatch):
    from eiraos.core.config import Settings, settings
    from eiraos.main import health_live

    assert Settings(RELEASE_SHA="abc123").RELEASE_SHA == "abc123"
    with pytest.raises(ValueError):
        Settings(RELEASE_SHA="bad release sha")
    monkeypatch.setattr(settings, "RELEASE_SHA", "qualified-sha")
    assert (await health_live())["release_sha"] == "qualified-sha"


def test_staging_runs_performance_gate_for_exact_release():
    from pathlib import Path

    script = (Path(__file__).parents[1] / "deploy/staging_deploy.sh").read_text()
    assert "scripts/f8_performance_gate.py" in script
    assert '--require-release "$GIT_SHA"' in script
    assert 'GIT_SHA="$(git rev-parse HEAD)"' in script
