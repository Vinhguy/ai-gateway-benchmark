#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ( "$1" != "bifrost" && "$1" != "litellm" ) ]]; then
  echo "usage: $0 bifrost|litellm" >&2
  exit 2
fi

gateway=$1
server_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$server_dir"
env_file=${BENCHMARK_ENV_FILE:-"$server_dir/.env"}
state_dir=${STATE_DIR:-"$server_dir/.state"}
docker_bin=${DOCKER_BIN:-docker}

if [[ ! -f "$env_file" ]]; then
  echo "server/.env is required; copy .env.example and review the local test keys" >&2
  exit 2
fi

"$server_dir/scripts/guard-server.sh" check
compose=("$docker_bin" compose --env-file "$env_file" --profile bifrost --profile litellm -f compose.yaml -p ai-gateway-benchmark)

# Clear either gateway even when the state file was lost during a host restart.
for service in bifrost litellm; do
  container_id=$("${compose[@]}" ps -q "$service")
  if [[ -n "$container_id" ]]; then
    "${compose[@]}" stop "$service"
    "${compose[@]}" rm -f "$service"
  fi
done

"${compose[@]}" up -d mocker "$gateway"
mkdir -p "$state_dir"
printf '%s\n' "$gateway" > "$state_dir/active-gateway"
echo "Started $gateway with the shared mock provider. Run guard-server.sh monitor in another terminal during the benchmark."
