from report import validate_result


def valid_result():
    return {
        "gateway": "bifrost",
        "gateway_version": "v2.2.6",
        "mocker_commit": "2c416fb234bf4abac25cf61f4470fc2528362afd",
        "configured_vus": 5000,
        "max_in_flight_limit": 1000,
        "observed_max_in_flight": 950,
        "completed": 1000,
        "failed": 0,
        "dropped": 0,
    }


def test_report_accepts_result_inside_success_and_resource_limits():
    report = validate_result(
        valid_result(),
        [{"host_available_mb": "3500", "process_private_mb": "600", "cpu_cores_used": "4"}],
        [{"mem_available_mb": "3000", "container": "gateway", "cpu_cores": "5", "memory_mb": "4000"}],
    )
    assert report["valid"] is True
    assert report["reasons"] == []


def test_low_memory_abort_and_memory_cap_event_invalidates_run():
    result = valid_result()
    result["memory_cap_event"] = True
    report = validate_result(
        result,
        [{"host_available_mb": "1900", "process_private_mb": "8192", "cpu_cores_used": "2"}],
        [],
    )
    assert report["valid"] is False
    assert "memory_cap_event" in report["reasons"]
    assert "host_available_below_2_gib" in report["reasons"]


def test_drops_success_rate_cpu_saturation_and_guest_low_memory_invalidate_run():
    result = valid_result()
    result.update(completed=998, failed=2, dropped=1)
    report = validate_result(
        result,
        [{"host_available_mb": "4000", "process_private_mb": "100", "cpu_cores_used": "8"}],
        [{"linux_mem_available_kb": "1843200", "container": "gateway", "cpu_percent": "800%", "memory_usage": "6000MiB / 6GiB"}],
    )
    assert report["valid"] is False
    assert {"success_rate_below_99_9_percent", "dropped_work", "generator_cpu_saturation", "guest_available_below_2_gib"}.issubset(report["reasons"])
