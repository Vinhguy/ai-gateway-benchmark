#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
temp_dir=$(mktemp -d "$root/../.server-test-tmp.XXXXXX")
trap 'rm -rf "$temp_dir"' EXIT

cat > "$temp_dir/meminfo-ok" <<'EOF'
MemTotal:       16000000 kB
MemAvailable:    4000000 kB
EOF
cat > "$temp_dir/meminfo-low" <<'EOF'
MemTotal:       16000000 kB
MemAvailable:    1000000 kB
EOF
cat > "$temp_dir/docker" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DOCKER_LOG"
if [[ " $* " == *" ps -q "* ]]; then
  printf 'container-id\n'
fi
EOF
chmod +x "$temp_dir/docker"
touch "$temp_dir/.env"
export DOCKER_BIN="$temp_dir/docker"
export DOCKER_LOG="$temp_dir/docker.log"
export BENCHMARK_ENV_FILE="$temp_dir/.env"
export STATE_DIR="$temp_dir/state"
export MEMINFO_PATH="$temp_dir/meminfo-ok"

"$root/scripts/guard-server.sh" check
if MEMINFO_PATH="$temp_dir/meminfo-low" "$root/scripts/guard-server.sh" check; then
  echo 'guard accepted less than 2 GiB available RAM' >&2
  exit 1
fi

mkdir -p "$STATE_DIR"
printf 'bifrost\n' > "$STATE_DIR/active-gateway"
if MEMINFO_PATH="$temp_dir/meminfo-low" "$root/scripts/guard-server.sh" monitor 1; then
  echo 'guard monitor did not exit after low-memory stop' >&2
  exit 1
fi
grep -q 'stop bifrost' "$DOCKER_LOG"
[[ ! -e "$STATE_DIR/active-gateway" ]]

if "$root/scripts/select-gateway.sh" invalid >/dev/null 2>&1; then
  echo 'selector accepted an unknown gateway' >&2
  exit 1
fi

"$root/scripts/select-gateway.sh" litellm >/dev/null
awk '
  / up -d mocker litellm$/ { up=NR }
  / stop / && !up { stopped=NR }
  END { exit !(up > 0 && stopped > 0 && stopped < up) }
' "$DOCKER_LOG"

echo 'server script tests passed'
