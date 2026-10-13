from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp


MODEL = "openai/gpt-4o-mini"
GATEWAY_VERSIONS = {"bifrost": "v2.2.6", "litellm": "v1.105.0", "direct-mocker": "2c416fb"}
MAX_LATENCY_SAMPLES = 50_000
MAX_RESPONSE_CHUNK = 8192
REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class LoadConfig:
    target_url: str
    vu_count: int
    max_in_flight: int
    timeout_seconds: float
    run_id: str
    think_time_min: float = 2.0
    think_time_max: float = 5.0
    api_key: str = "sk-benchmark-only-not-a-secret"
    gateway: str = "bifrost"
    gateway_version: str | None = None
    mocker_commit: str = "unknown"

    def __post_init__(self) -> None:
        parsed = urlparse(self.target_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("target_url must be an absolute HTTP(S) URL")
        if not 1 <= self.vu_count <= 5000:
            raise ValueError("vu_count must be between 1 and 5000")
        if not 1 <= self.max_in_flight <= min(1000, self.vu_count):
            raise ValueError("max_in_flight must be between 1 and min(1000, vu_count)")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.gateway not in GATEWAY_VERSIONS:
            raise ValueError("gateway must be bifrost, litellm, or direct-mocker")
        if self.gateway_version is None:
            object.__setattr__(self, "gateway_version", GATEWAY_VERSIONS[self.gateway])
        if self.gateway_version != GATEWAY_VERSIONS[self.gateway]:
            raise ValueError(f"gateway_version must match pinned {GATEWAY_VERSIONS[self.gateway]}")
        if not re.fullmatch(r"(?:[0-9a-f]{7,40}|unknown)", self.mocker_commit):
            raise ValueError("mocker_commit must be a Git hash or unknown")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", self.run_id):
            raise ValueError("run_id must be 1-80 safe filename characters")
        if (
            not math.isfinite(self.think_time_min)
            or not math.isfinite(self.think_time_max)
            or self.think_time_min < 0
            or self.think_time_max < self.think_time_min
            or self.think_time_max > 60
        ):
            raise ValueError("think-time range must satisfy 0 <= min <= max <= 60 seconds")


@dataclass
class Metrics:
    configured_vus: int
    in_flight_limit: int
    seed: int
    gateway: str = "unknown"
    gateway_version: str = "unknown"
    mocker_commit: str = "unknown"
    started_at: float = field(default_factory=time.perf_counter)
    completed: int = 0
    failed: int = 0
    completed_in_window: int = 0
    failed_in_window: int = 0
    completed_during_drain: int = 0
    failed_during_drain: int = 0
    http_errors: int = 0
    network_errors: int = 0
    admission_delayed: int = 0
    dropped: int = 0
    observed_max_in_flight: int = 0
    _in_flight: int = 0
    _latency_samples_ms: list[float] = field(default_factory=list)
    _admission_samples_ms: list[float] = field(default_factory=list)
    _latency_observations: int = 0
    _admission_observations: int = 0
    _window_latency_samples_ms: dict[str, list[float]] = field(default_factory=dict)
    _window_observations: dict[str, int] = field(default_factory=dict)
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def _sample(self, values: list[float], value: float, observation_count: int) -> None:
        if len(values) < MAX_LATENCY_SAMPLES:
            values.append(value)
            return
        index = self._rng.randrange(observation_count)
        if index < MAX_LATENCY_SAMPLES:
            values[index] = value

    def record_admission_delay(self, delay_ms: float) -> None:
        self._admission_observations += 1
        if delay_ms > 0.1:
            self.admission_delayed += 1
        self._sample(self._admission_samples_ms, delay_ms, self._admission_observations)

    def begin_request(self) -> None:
        self._in_flight += 1
        self.observed_max_in_flight = max(self.observed_max_in_flight, self._in_flight)

    def end_request(
        self,
        *,
        latency_ms: float,
        succeeded: bool,
        network_error: bool = False,
        time_window: str | None = None,
        in_measurement_window: bool = True,
    ) -> None:
        self._in_flight -= 1
        self._latency_observations += 1
        self._sample(self._latency_samples_ms, latency_ms, self._latency_observations)
        if time_window is not None:
            window_samples = self._window_latency_samples_ms.setdefault(time_window, [])
            window_count = self._window_observations.get(time_window, 0) + 1
            self._window_observations[time_window] = window_count
            self._sample(window_samples, latency_ms, window_count)
        if succeeded:
            self.completed += 1
            if in_measurement_window:
                self.completed_in_window += 1
            else:
                self.completed_during_drain += 1
        else:
            self.failed += 1
            if in_measurement_window:
                self.failed_in_window += 1
            else:
                self.failed_during_drain += 1
            if network_error:
                self.network_errors += 1
            else:
                self.http_errors += 1

    @staticmethod
    def _percentile(samples: list[float], percentile: float) -> float | None:
        if not samples:
            return None
        ordered = sorted(samples)
        index = max(0, math.ceil(percentile * len(ordered)) - 1)
        return round(ordered[index], 3)

    def summary(
        self,
        *,
        profile: str,
        duration_seconds: float | None = None,
        duration_drain_seconds: float = 0,
    ) -> dict[str, Any]:
        elapsed = duration_seconds if duration_seconds is not None else time.perf_counter() - self.started_at
        elapsed = round(max(elapsed, 1e-9), 6)
        latencies = self._latency_samples_ms
        admission = self._admission_samples_ms
        total = self.completed + self.failed
        in_window_total = self.completed_in_window + self.failed_in_window
        full_elapsed = elapsed + max(0.0, duration_drain_seconds)
        first_p95 = self._percentile(self._window_latency_samples_ms.get("first_half", []), 0.95)
        final_p95 = self._percentile(self._window_latency_samples_ms.get("final_half", []), 0.95)
        drift = None
        if first_p95 is not None and final_p95 is not None and first_p95 > 0:
            drift = round(((final_p95 - first_p95) / first_p95) * 100, 2)
        return {
            "run_id": "",
            "profile": profile,
            "gateway": self.gateway,
            "gateway_version": self.gateway_version,
            "mocker_commit": self.mocker_commit,
            "model": MODEL,
            "configured_vus": self.configured_vus,
            "max_in_flight_limit": self.in_flight_limit,
            "observed_max_in_flight": self.observed_max_in_flight,
            "duration_seconds": elapsed,
            "completed": self.completed,
            "failed": self.failed,
            "completed_in_measurement_window": self.completed_in_window,
            "failed_in_measurement_window": self.failed_in_window,
            "completed_during_drain": self.completed_during_drain,
            "failed_during_drain": self.failed_during_drain,
            "drain_seconds": round(max(0.0, duration_drain_seconds), 6),
            "http_errors": self.http_errors,
            "network_errors": self.network_errors,
            "dropped": self.dropped,
            "admission_delayed": self.admission_delayed,
            "rps": round(in_window_total / elapsed, 3),
            "drain_inclusive_rps": round(total / full_elapsed, 3),
            "success_rate": round(self.completed / total, 6) if total else 0.0,
            "latency_sample_count": len(latencies),
            "latency_percentile_method": "uniform reservoir sample, max 50000 observations",
            "latency_p50_ms": self._percentile(latencies, 0.50),
            "latency_p95_ms": self._percentile(latencies, 0.95),
            "latency_p99_ms": self._percentile(latencies, 0.99),
            "latency_p95_first_half_ms": first_p95,
            "latency_p95_final_half_ms": final_p95,
            "latency_p95_drift_percent": drift,
            "admission_delay_p95_ms": self._percentile(admission, 0.95),
        }


class LoadGenerator:
    def __init__(self, config: LoadConfig) -> None:
        self.config = config
        seed = int.from_bytes(hashlib.sha256(config.run_id.encode("utf-8")).digest()[:8], "big")
        self.metrics = Metrics(
            config.vu_count,
            config.max_in_flight,
            seed,
            config.gateway,
            config.gateway_version,
            config.mocker_commit,
        )
        self._semaphore = asyncio.Semaphore(config.max_in_flight)
        self._session: aiohttp.ClientSession | None = None
        self._sustained_started_at: float | None = None
        self._sustained_split_seconds: float | None = None
        self._sustained_duration_seconds: float | None = None

    async def __aenter__(self) -> LoadGenerator:
        connector = aiohttp.TCPConnector(
            limit=self.config.max_in_flight,
            limit_per_host=self.config.max_in_flight,
            keepalive_timeout=30,
        )
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
        )
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _drain_response(self, response: aiohttp.ClientResponse) -> None:
        async for _chunk in response.content.iter_chunked(MAX_RESPONSE_CHUNK):
            pass

    async def _send_one(self, stop_event: asyncio.Event | None = None) -> bool:
        if self._session is None:
            raise RuntimeError("LoadGenerator must be used as an async context manager")

        queued_at = time.perf_counter()
        async with self._semaphore:
            admission_ms = (time.perf_counter() - queued_at) * 1000
            if stop_event is not None and stop_event.is_set():
                return False
            self.metrics.record_admission_delay(admission_ms)
            self.metrics.begin_request()
            started = time.perf_counter()
            request_elapsed = None
            if self._sustained_started_at is not None:
                request_elapsed = started - self._sustained_started_at
            succeeded = False
            network_error = False
            try:
                payload = {
                    "model": MODEL,
                    "messages": [{"role": "user", "content": "benchmark ping"}],
                    "max_tokens": 8,
                    "stream": False,
                }
                async with self._session.post(self.config.target_url, json=payload) as response:
                    await self._drain_response(response)
                    succeeded = 200 <= response.status < 300
            except (aiohttp.ClientError, asyncio.TimeoutError):
                network_error = True
            finally:
                latency_ms = (time.perf_counter() - started) * 1000
                time_window = None
                if request_elapsed is not None and self._sustained_split_seconds is not None:
                    time_window = "first_half" if request_elapsed <= self._sustained_split_seconds else "final_half"
                in_measurement_window = (
                    self._sustained_duration_seconds is None
                    or time.perf_counter() - self._sustained_started_at <= self._sustained_duration_seconds
                )
                self.metrics.end_request(
                    latency_ms=latency_ms,
                    succeeded=succeeded,
                    network_error=network_error,
                    time_window=time_window,
                    in_measurement_window=in_measurement_window,
                )
            return succeeded

    async def run_burst(self, request_count: int) -> dict[str, Any]:
        if not 1 <= request_count <= min(self.config.vu_count, self.config.max_in_flight):
            raise ValueError("burst request_count must be between 1 and min(vu_count, max_in_flight)")
        barrier = asyncio.Barrier(request_count)

        async def user_request() -> None:
            await barrier.wait()
            await self._send_one()

        started = time.perf_counter()
        await asyncio.gather(*(user_request() for _ in range(request_count)))
        return self.metrics.summary(profile="burst", duration_seconds=time.perf_counter() - started)

    async def run_sustained(self, duration_seconds: float) -> dict[str, Any]:
        if not math.isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        stop_event = asyncio.Event()
        measurement_started = time.perf_counter()
        self._sustained_started_at = measurement_started
        self._sustained_split_seconds = duration_seconds / 2
        self._sustained_duration_seconds = duration_seconds

        async def user_loop(worker_id: int) -> None:
            rng = random.Random(f"{self.config.run_id}:{worker_id}")
            while not stop_event.is_set():
                delay = rng.uniform(self.config.think_time_min, self.config.think_time_max)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=delay)
                    break
                except asyncio.TimeoutError:
                    pass
                if stop_event.is_set():
                    break
                await self._send_one(stop_event)

        workers = [asyncio.create_task(user_loop(worker_id)) for worker_id in range(self.config.vu_count)]
        try:
            measurement_deadline = measurement_started + duration_seconds
            while True:
                remaining = measurement_deadline - time.perf_counter()
                if remaining <= 0:
                    break
                # Loop timer clocks can have coarse resolution on Windows; recheck against
                # the same high-resolution clock used for reported duration/RPS.
                await asyncio.sleep(min(remaining, 1.0))
        finally:
            measurement_ended = time.perf_counter()
            stop_event.set()
            await asyncio.gather(*workers)
        drain_ended = time.perf_counter()
        # Drain in-flight requests for clean shutdown, but do not add that drain time to the hold window.
        return self.metrics.summary(
            profile="sustained",
            duration_seconds=measurement_ended - measurement_started,
            duration_drain_seconds=drain_ended - measurement_ended,
        )


def write_result(summary: dict[str, Any], run_id: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        **summary,
        "run_id": run_id,
    }
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(output_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Direct async HTTP load generator for AI gateways")
    parser.add_argument("--target-url", required=True)
    parser.add_argument("--vu-count", type=int, required=True)
    parser.add_argument("--max-in-flight", type=int, required=True)
    parser.add_argument("--profile", choices=("burst", "sustained"), required=True)
    parser.add_argument("--duration-seconds", type=float, default=600)
    parser.add_argument("--burst-count", type=int, default=None)
    parser.add_argument("--timeout-seconds", type=float, default=30)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--gateway", choices=tuple(GATEWAY_VERSIONS), default="bifrost")
    parser.add_argument("--gateway-version", default=None)
    parser.add_argument("--mocker-commit", default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--think-time-min", type=float, default=2)
    parser.add_argument("--think-time-max", type=float, default=5)
    parser.add_argument("--job-memory-gb", type=int, default=8)
    parser.add_argument("--job-cpu-cores", type=int, default=8)
    parser.add_argument("--skip-job-limits", action="store_true", help=argparse.SUPPRESS)
    return parser


async def _run_cli(args: argparse.Namespace) -> dict[str, Any]:
    gateway = args.gateway
    gateway_version = args.gateway_version or GATEWAY_VERSIONS[gateway]
    mocker_commit = args.mocker_commit or os.environ.get("MOCKER_COMMIT")
    if not mocker_commit:
        try:
            mocker_commit = subprocess.run(
                ["git", "-C", str(REPO_ROOT / "upstream-benchmarking"), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            mocker_commit = "unknown"
    config = LoadConfig(
        target_url=args.target_url,
        vu_count=args.vu_count,
        max_in_flight=args.max_in_flight,
        timeout_seconds=args.timeout_seconds,
        run_id=args.run_id,
        think_time_min=args.think_time_min,
        think_time_max=args.think_time_max,
        api_key=os.environ.get("BENCHMARK_API_KEY", "sk-benchmark-only-not-a-secret"),
        gateway=gateway,
        gateway_version=gateway_version,
        mocker_commit=mocker_commit,
    )
    async with LoadGenerator(config) as load:
        if args.profile == "burst":
            request_count = args.burst_count or min(config.vu_count, config.max_in_flight)
            return await load.run_burst(request_count)
        return await load.run_sustained(args.duration_seconds)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if os.name == "nt" and not args.skip_job_limits:
            from windows_job import apply_current_process_limits

            apply_current_process_limits(args.job_memory_gb, args.job_cpu_cores)
        summary = asyncio.run(_run_cli(args))
        output = args.output or REPO_ROOT / "results" / f"{args.run_id}.json"
        write_result(summary, args.run_id, output)
        print(json.dumps({**summary, "run_id": args.run_id, "output": str(output)}, indent=2))
        return 0 if summary["failed"] == 0 and summary["dropped"] == 0 else 1
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"loadgen: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
