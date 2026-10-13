#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 RUN_ID [poll-seconds]" >&2
  exit 2
fi
run_id=$1
interval=${2:-1}
if [[ ! "$run_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$ || ! "$interval" =~ ^[1-9][0-9]*$ ]]; then
  echo "RUN_ID or poll interval is invalid" >&2
  exit 2
fi

server_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
result_dir="$server_dir/results"
result_file="$result_dir/$run_id-server-resources.csv"
mkdir -p "$result_dir"
env_file=${BENCHMARK_ENV_FILE:-"$server_dir/.env"}
docker_bin=${DOCKER_BIN:-docker}
compose=("$docker_bin" compose --env-file "$env_file" --profile bifrost --profile litellm -f "$server_dir/compose.yaml" -p ai-gateway-benchmark)
printf 'timestamp_utc,linux_mem_available_kb,container,cpu_percent,memory_usage,memory_percent\n' > "$result_file"

while true; do
  timestamp=$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)
  available_kb=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
  container_ids=$("${compose[@]}" ps -q)
  if [[ -z "$container_ids" ]]; then
    printf '%s,%s,,,,\n' "$timestamp" "$available_kb" >> "$result_file"
  else
    while IFS= read -r container_id; do
      [[ -z "$container_id" ]] && continue
      stats=$("$docker_bin" stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}}' "$container_id")
      printf '%s,%s,%s\n' "$timestamp" "$available_kb" "$stats" >> "$result_file"
    done <<< "$container_ids"
  fi
  sleep "$interval"
done
