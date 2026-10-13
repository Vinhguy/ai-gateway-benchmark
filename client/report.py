from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any


def _number(row: dict[str, Any], key: str) -> float | None:
    try:
        return float(str(row.get(key, "")).strip())
    except (TypeError, ValueError):
        return None


def _memory_mb(value: str) -> float | None:
    match = re.match(r"^\s*([0-9.]+)\s*([KMGT]i?B)?", value, re.IGNORECASE)
    if not match:
        return None
    amount = float(match.group(1))
    unit = (match.group(2) or "MB").upper()
    scale = {"B": 1 / 1_048_576, "KB": 1 / 1024, "KIB": 1 / 1024,
             "MB": 1, "MIB": 1, "GB": 1024, "GIB": 1024,
             "TB": 1024 * 1024, "TIB": 1024 * 1024}
    return amount * scale[unit]


def validate_result(
    result: dict[str, Any],
    client_rows: list[dict[str, Any]] | None = None,
    server_rows: list[dict[str, Any]] | None = None,
    server_host_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    reasons: set[str] = set()
    total = int(result.get("completed", 0)) + int(result.get("failed", 0))
    success_rate = int(result.get("completed", 0)) / total if total else 0
    if success_rate < 0.999:
        reasons.add("success_rate_below_99_9_percent")
    if int(result.get("dropped", 0)) > 0:
        reasons.add("dropped_work")
    if int(result.get("observed_max_in_flight", 0)) > int(result.get("max_in_flight_limit", 0)):
        reasons.add("in_flight_limit_exceeded")
    if int(result.get("configured_vus", 0)) != 5000 or int(result.get("max_in_flight_limit", 0)) != 1000:
        reasons.add("workload_does_not_match_comparison_profile")
    profile = result.get("profile")
    if profile == "burst":
        if total != 1000 or int(result.get("observed_max_in_flight", 0)) != 1000:
            reasons.add("burst_did_not_reach_1000_concurrent_requests")
    elif profile == "sustained":
        if float(result.get("duration_seconds", 0)) < 600:
            reasons.add("sustained_run_shorter_than_10_minutes")
        drift = result.get("latency_p95_drift_percent")
        if drift is None or abs(float(drift)) >= 20:
            reasons.add("sustained_p95_drift_missing_or_at_least_20_percent")
    else:
        reasons.add("unsupported_comparison_profile")
    if result.get("gateway") not in {"bifrost", "litellm"}:
        reasons.add("diagnostic_run_not_comparable")
    if result.get("memory_cap_event"):
        reasons.add("memory_cap_event")
    if result.get("aborted") or result.get("event"):
        reasons.add("aborted_run")
    if result.get("gateway_version") in (None, "", "unknown"):
        reasons.add("missing_gateway_version")
    if result.get("mocker_commit") in (None, "", "unknown"):
        reasons.add("missing_mocker_commit")

    if not client_rows or not any(
        all(_number(row, key) is not None for key in ("host_available_mb", "process_private_mb", "cpu_cores_used"))
        for row in client_rows
    ):
        reasons.add("missing_client_resource_samples")
    if not server_rows or not any(
        _number(row, "linux_mem_available_kb") is not None
        and row.get("cpu_percent")
        and row.get("memory_usage")
        for row in server_rows
    ):
        reasons.add("missing_guest_resource_samples")
    if not server_host_rows or not any(_number(row, "host_available_mb") is not None for row in server_host_rows):
        reasons.add("missing_server_host_resource_samples")

    for row in client_rows or []:
        available = _number(row, "host_available_mb")
        private = _number(row, "process_private_mb")
        cpu = _number(row, "cpu_cores_used")
        if available is not None and available < 2048:
            reasons.add("host_available_below_2_gib")
        if private is not None and private >= 8192 * 0.95:
            reasons.add("generator_memory_cap_reached")
        if cpu is not None and cpu >= 7.6:
            reasons.add("generator_cpu_saturation")

    for row in server_rows or []:
        available_kb = _number(row, "linux_mem_available_kb")
        if available_kb is not None and available_kb < 2 * 1024 * 1024:
            reasons.add("guest_available_below_2_gib")
        usage = str(row.get("memory_usage", "")).split("/", 1)[0].strip()
        used_mb = _memory_mb(usage) if usage else None
        limit_mb = _memory_mb(row.get("memory_usage", "").split("/", 1)[1].strip()) if "/" in str(row.get("memory_usage", "")) else None
        if used_mb is not None and limit_mb and used_mb >= limit_mb * 0.95:
            reasons.add("container_memory_cap_reached")
        cpu_percent = str(row.get("cpu_percent", "")).strip().rstrip("%")
        try:
            cpu_limit = 100 if "mocker" in str(row.get("container", "")).lower() else 800
            if float(cpu_percent) >= cpu_limit * 0.95:
                reasons.add("container_cpu_cap_reached")
        except ValueError:
            pass

    for row in server_host_rows or []:
        available = _number(row, "host_available_mb")
        if available is not None and available < 2048:
            reasons.add("server_host_available_below_2_gib")

    return {"valid": not reasons, "reasons": sorted(reasons), "success_rate": round(success_rate, 6)}


def _read_csv(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a benchmark run before comparing it")
    parser.add_argument("result", type=Path)
    parser.add_argument("--client-resources", type=Path)
    parser.add_argument("--server-resources", type=Path)
    parser.add_argument("--server-host-resources", type=Path)
    parser.add_argument("--abort-event", type=Path)
    args = parser.parse_args()

    result = json.loads(args.result.read_text(encoding="utf-8"))
    client_rows = _read_csv(args.client_resources)
    server_rows = _read_csv(args.server_resources)
    server_host_rows = _read_csv(args.server_host_resources)
    if args.abort_event and args.abort_event.exists():
        result["aborted"] = True
    validation = validate_result(result, client_rows, server_rows, server_host_rows)
    output_path = args.result.with_name(args.result.stem + "-validation.json")
    output_path.write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(validation, indent=2))
    return 0 if validation["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
