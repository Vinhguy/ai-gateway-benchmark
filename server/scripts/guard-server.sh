#!/usr/bin/env bash
set -euo pipefail

server_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
meminfo_path=${MEMINFO_PATH:-/proc/meminfo}
threshold_kb=${MIN_AVAILABLE_KB:-2097152}
state_dir=${STATE_DIR:-"$server_dir/.state"}
state_file="$state_dir/active-gateway"
env_file=${BENCHMARK_ENV_FILE:-"$server_dir/.env"}
docker_bin=${DOCKER_BIN:-docker}
compose=("$docker_bin" compose --env-file "$env_file" --profile bifrost --profile litellm -f "$server_dir/compose.yaml" -p ai-gateway-benchmark)

available_kb() {
  awk '/^MemAvailable:/ {print $2; found=1} END {if (!found) exit 1}' "$meminfo_path"
}

check_memory() {
  local available
  available=$(available_kb) || { echo "cannot read MemAvailable from $meminfo_path" >&2; return 2; }
  if (( available < threshold_kb )); then
    echo "available RAM ${available} KiB is below ${threshold_kb} KiB" >&2
    return 1
  fi
}

case ${1:-} in
  check)
    check_memory
    ;;
  monitor)
    interval=${2:-1}
    if [[ ! "$interval" =~ ^[1-9][0-9]*$ ]]; then
      echo "monitor interval must be a positive integer number of seconds" >&2
      exit 2
    fi
    while true; do
      if ! check_memory; then
        if [[ -f "$state_file" ]]; then
          gateway=$(<"$state_file")
          if [[ "$gateway" == "bifrost" || "$gateway" == "litellm" ]]; then
            container_id=$("${compose[@]}" ps -q "$gateway")
            if [[ -n "$container_id" ]]; then
              "${compose[@]}" stop "$gateway"
            fi
            rm -f "$state_file"
          fi
        fi
        exit 1
      fi
      sleep "$interval"
    done
    ;;
  *)
    echo "usage: $0 check|monitor [poll-seconds]" >&2
    exit 2
    ;;
esac
