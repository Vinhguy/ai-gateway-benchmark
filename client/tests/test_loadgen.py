import asyncio
import importlib
import json
from pathlib import Path

import pytest
from aiohttp import web


def loadgen_module():
    try:
        return importlib.import_module("loadgen")
    except ImportError as exc:
        pytest.fail(f"direct HTTP load generator is not implemented: {exc}")


def test_load_config_rejects_population_or_inflight_above_plan_limits():
    module = loadgen_module()
    with pytest.raises(ValueError):
        module.LoadConfig("http://localhost:8080/v1/chat/completions", 5001, 1000, 1, "invalid")
    with pytest.raises(ValueError):
        module.LoadConfig("http://localhost:8080/v1/chat/completions", 5000, 1001, 1, "invalid")


def test_result_records_gateway_and_pinned_versions():
    module = loadgen_module()

    async def scenario():
        config = module.LoadConfig(
            "http://127.0.0.1:1/v1/chat/completions", 1, 1, 1, "metadata-test",
            gateway="bifrost", gateway_version="v2.2.6", mocker_commit="2c416fb234bf4abac25cf61f4470fc2528362afd",
        )
        async with module.LoadGenerator(config) as load:
            summary = load.metrics.summary(profile="burst", duration_seconds=1)
        assert summary["gateway"] == "bifrost"
        assert summary["gateway_version"] == "v2.2.6"
        assert summary["mocker_commit"] == "2c416fb234bf4abac25cf61f4470fc2528362afd"

    asyncio.run(scenario())


async def start_test_server(handler):
    app = web.Application()
    app.router.add_post("/v1/chat/completions", handler)
    app_runner = web.AppRunner(app)
    await app_runner.setup()
    site = web.TCPSite(app_runner, "127.0.0.1", 0, backlog=2048)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return app_runner, f"http://127.0.0.1:{port}/v1/chat/completions"


def test_burst_releases_1000_requests_together_and_caps_inflight():
    module = loadgen_module()

    async def scenario():
        active = 0
        peak = 0
        all_started = asyncio.Event()

        async def handler(_request):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if active == 1000:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), timeout=20)
            active -= 1
            return web.json_response({"ok": True})

        app_runner, url = await start_test_server(handler)
        try:
            config = module.LoadConfig(url, 5000, 1000, 10, "burst-test")
            async with module.LoadGenerator(config) as load:
                summary = await load.run_burst(1000)
            assert peak == 1000
            assert summary["completed"] == 1000
            assert summary["observed_max_in_flight"] == 1000
            assert summary["configured_vus"] == 5000
            assert summary["rps"] > 0
        finally:
            await app_runner.cleanup()

    asyncio.run(scenario())


def test_sustained_profile_never_exceeds_inflight_cap_and_drains_responses():
    module = loadgen_module()

    async def scenario():
        active = 0
        peak = 0

        async def handler(request):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.005)
            active -= 1
            return web.json_response({"ok": True, "body": "x" * 128})

        app_runner, url = await start_test_server(handler)
        try:
            config = module.LoadConfig(
                url,
                20,
                5,
                30,
                "sustain-test",
                think_time_min=0,
                think_time_max=0,
            )
            async with module.LoadGenerator(config) as load:
                summary = await load.run_sustained(0.15)
            assert 1 <= peak <= 5
            assert summary["observed_max_in_flight"] <= 5
            assert summary["failed"] == 0
            assert summary["completed"] > 0
            assert summary["latency_sample_count"] <= 50000
            assert summary["latency_p95_first_half_ms"] is not None
            assert summary["latency_p95_final_half_ms"] is not None
            assert summary["latency_p95_drift_percent"] is not None
            assert summary["rps"] == round(summary["completed"] / summary["duration_seconds"], 3)
            result_path = Path(__file__).parent / "sustain-test-result.json"
            module.write_result(summary, "sustain-test", result_path)
            report = json.loads(result_path.read_text(encoding="utf-8"))
            assert report["run_id"] == "sustain-test"
            assert report["configured_vus"] == 20
            assert "observed_max_in_flight" in report
            result_path.unlink()
        finally:
            await app_runner.cleanup()

    asyncio.run(scenario())


def test_sustained_profile_represents_5000_workers_without_exceeding_cap():
    module = loadgen_module()

    async def scenario():
        config = module.LoadConfig(
            "http://127.0.0.1:1/v1/chat/completions",
            5000,
            1000,
            1,
            "population-test",
            think_time_min=5,
            think_time_max=5,
        )
        async with module.LoadGenerator(config) as load:
            summary = await load.run_sustained(0.02)
        assert summary["configured_vus"] == 5000
        assert summary["max_in_flight_limit"] == 1000
        assert summary["observed_max_in_flight"] == 0

    asyncio.run(scenario())
