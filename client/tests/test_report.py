from report import validate_result


def valid_result():
    return {
        "gateway": "bifrost",
        "gateway_version": "v2.2.6",
        "mocker_commit": "2c416fb234bf4abac25cf61f4470fc2528362afd",
        "profile": "burst",
        "duration_seconds": 2,
        "configured_vus": 5000,
        "max_in_flight_limit": 1000,
        "observed_max_in_flight": 1000,
        "completed": 1000,
        "failed": 0,
        "dropped": 0,
    }


def resource_rows():
    return (
        [
            {"timestamp_utc": "2026-10-13T10:00:00+00:00", "host_available_mb": "3500", "process_private_mb": "600", "cpu_cores_used": "4"},
            {"timestamp_utc": "2026-10-13T10:00:02+00:00", "host_available_mb": "3500", "process_private_mb": "600", "cpu_cores_used": "4"},
        ],
        [
            {"timestamp_utc": "2026-10-13T10:00:00+00:00", "linux_mem_available_kb": "3000000", "container": "gateway", "cpu_percent": "5%", "memory_usage": "4000MiB / 6GiB"},
            {"timestamp_utc": "2026-10-13T10:00:02+00:00", "linux_mem_available_kb": "3000000", "container": "gateway", "cpu_percent": "5%", "memory_usage": "4000MiB / 6GiB"},
        ],
        [
            {"timestamp_utc": "2026-10-13T10:00:00+00:00", "host_available_mb": "3500"},
            {"timestamp_utc": "2026-10-13T10:00:02+00:00", "host_available_mb": "3500"},
        ],
    )


def test_report_accepts_result_inside_success_and_resource_limits():
    report = validate_result(valid_result(), *resource_rows())
    assert report["valid"] is True
    assert report["reasons"] == []


def test_low_memory_abort_and_memory_cap_event_invalidates_run():
    result = valid_result()
    result["memory_cap_event"] = True
    report = validate_result(
        result,
        [{"host_available_mb": "1900", "process_private_mb": "8192", "cpu_cores_used": "2"}],
        [],
        [{"host_available_mb": "1900"}],
    )
    assert report["valid"] is False
    assert "memory_cap_event" in report["reasons"]
    assert "host_available_below_2_gib" in report["reasons"]
    assert "server_host_available_below_2_gib" in report["reasons"]


def test_drops_success_rate_cpu_saturation_and_guest_low_memory_invalidate_run():
    result = valid_result()
    result.update(completed=998, failed=2, dropped=1)
    report = validate_result(
        result,
        [{"host_available_mb": "4000", "process_private_mb": "100", "cpu_cores_used": "8"}],
        [{"linux_mem_available_kb": "1843200", "container": "gateway", "cpu_percent": "800%", "memory_usage": "6000MiB / 6GiB"}],
        [{"host_available_mb": "4000"}],
    )
    assert report["valid"] is False
    assert {
        "success_rate_below_99_9_percent",
        "dropped_work",
        "generator_cpu_saturation",
        "guest_available_below_2_gib",
        "container_memory_cap_reached",
        "container_cpu_cap_reached",
    }.issubset(report["reasons"])


def test_missing_measurement_evidence_and_sustained_drift_make_report_invalid():
    result = valid_result()
    result.update(profile="sustained", duration_seconds=600, latency_p95_drift_percent=20)
    report = validate_result(result)
    assert report["valid"] is False
    assert {
        "missing_client_resource_samples",
        "missing_guest_resource_samples",
        "missing_server_host_resource_samples",
        "sustained_p95_drift_missing_or_at_least_20_percent",
    }.issubset(report["reasons"])


def test_server_host_memory_floor_is_checked():
    report = validate_result(
        valid_result(),
        [{"host_available_mb": "4000", "process_private_mb": "500", "cpu_cores_used": "2"}],
        [{"linux_mem_available_kb": "3000000", "cpu_percent": "10%", "memory_usage": "100MiB / 6GiB"}],
        [{"host_available_mb": "1900"}],
    )
    assert "server_host_available_below_2_gib" in report["reasons"]


def test_single_resource_sample_cannot_validate_a_ten_minute_run():
    result = valid_result()
    result.update(profile="sustained", duration_seconds=600, latency_p95_drift_percent=1)
    timestamp = "2026-10-13T10:00:00+00:00"
    report = validate_result(
        result,
        [{"timestamp_utc": timestamp, "host_available_mb": "4000", "process_private_mb": "500", "cpu_cores_used": "2"}],
        [{"timestamp_utc": timestamp, "linux_mem_available_kb": "3000000", "cpu_percent": "10%", "memory_usage": "100MiB / 6GiB"}],
        [{"timestamp_utc": timestamp, "host_available_mb": "4000"}],
    )
    assert {
        "incomplete_client_resource_coverage",
        "incomplete_guest_resource_coverage",
        "incomplete_server_host_resource_coverage",
    }.issubset(report["reasons"])
