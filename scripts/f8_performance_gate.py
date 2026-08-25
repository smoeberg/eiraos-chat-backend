"""Bounded live latency/error gate for a qualified staging deployment."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class Sample:
    status: int
    duration_ms: float
    valid: bool


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


def summarize(samples: list[Sample]) -> dict:
    durations = [sample.duration_ms for sample in samples]
    errors = sum(not sample.valid for sample in samples)
    return {
        "requests": len(samples), "errors": errors,
        "error_rate": errors / len(samples) if samples else 1.0,
        "p50_ms": round(percentile(durations, 0.50), 3),
        "p95_ms": round(percentile(durations, 0.95), 3),
        "max_ms": round(max(durations, default=0.0), 3),
    }


async def run_scenario(client: httpx.AsyncClient, path: str, expected: int,
                       requests: int, concurrency: int) -> dict:
    semaphore = asyncio.Semaphore(concurrency)

    async def one() -> Sample:
        async with semaphore:
            started = time.perf_counter()
            try:
                response = await client.get(path)
                duration = (time.perf_counter() - started) * 1000
                return Sample(response.status_code, duration, response.status_code == expected)
            except httpx.HTTPError:
                return Sample(0, (time.perf_counter() - started) * 1000, False)

    return summarize(await asyncio.gather(*(one() for _ in range(requests))))


async def qualify(args) -> tuple[dict, bool]:
    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
    async with httpx.AsyncClient(base_url=args.base_url.rstrip("/"), timeout=args.timeout,
                                 limits=limits, trust_env=False) as client:
        live = await client.get("/health/live")
        release = live.json().get("release_sha") if live.status_code == 200 else None
        reports = {
            "health_live": await run_scenario(client, "/health/live", 200, args.requests, args.concurrency),
            "auth_rejection": await run_scenario(
                client, "/api/v1/organizations", 401, args.requests, args.concurrency,
            ),
        }
    passed = all(
        report["error_rate"] <= args.max_error_rate and report["p95_ms"] <= args.max_p95_ms
        for report in reports.values()
    ) and (not args.require_release or release == args.require_release)
    return {"release_sha": release, "limits": {
        "max_error_rate": args.max_error_rate, "max_p95_ms": args.max_p95_ms,
        "requests_per_scenario": args.requests, "concurrency": args.concurrency,
    }, "scenarios": reports, "passed": passed}, passed


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--base-url", required=True)
    result.add_argument("--requests", type=int, default=100)
    result.add_argument("--concurrency", type=int, default=10)
    result.add_argument("--max-p95-ms", type=float, default=500.0)
    result.add_argument("--max-error-rate", type=float, default=0.0)
    result.add_argument("--timeout", type=float, default=5.0)
    result.add_argument("--require-release")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.requests < 1 or args.concurrency < 1 or args.concurrency > args.requests:
        raise SystemExit("requests/concurrency must be positive and concurrency <= requests")
    report, passed = asyncio.run(qualify(args))
    print(json.dumps(report, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
