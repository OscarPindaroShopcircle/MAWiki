#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
command -v python3 >/dev/null || { printf '%s\n' 'python3 is required' >&2; exit 1; }

if [[ $# -ne 3 ]]; then
  printf 'Usage: %s <name> <cron-schedule> <command>\n' "$0" >&2
  exit 1
fi

NAME="$1"
SCHEDULE="$2"
COMMAND="$3"
TARGET_DIR="$ROOT_DIR/deploy/railway/production/cron/$NAME"

[[ "$NAME" =~ ^[a-z0-9][a-z0-9-]*$ ]] || { printf '%s\n' 'Name must use lowercase letters, numbers, and hyphens' >&2; exit 1; }
[[ ! -e "$TARGET_DIR" ]] || { printf 'Already exists: %s\n' "$TARGET_DIR" >&2; exit 1; }

mkdir -p "$TARGET_DIR"
schedule_toml="$(printf '%s' "$SCHEDULE" | python3 -c 'import json, sys; print(json.dumps(sys.stdin.read()))')"
command_toml="$(printf '%s' "$COMMAND" | python3 -c 'import json, sys; print(json.dumps(sys.stdin.read()))')"

cat > "$TARGET_DIR/railway.toml" <<EOF
[build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile"

[deploy]
cronSchedule = $schedule_toml
startCommand = $command_toml
restartPolicyType = "NEVER"
multiRegionConfig = { "europe-west4-drams3a" = { numReplicas = 1 } }
EOF

printf 'Created %s\nCommit and push it, then run:\n  deploy/railway/bin/provision-service.sh --project <project> --type cron --name %s\n' "$TARGET_DIR/railway.toml" "$NAME"
