#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PROJECT=""
ENVIRONMENT="production"
TYPE=""
NAME=""
SERVICE=""
WEB_SERVICE="MAWiki"
DATABASE_SERVICE="Postgres"
REPOSITORY="OscarPindaroShopcircle/MAWiki"
BRANCH="main"
EU_REGION="europe-west4-drams3a"

usage() {
  cat <<EOF
Usage: $0 --project <name-or-id> --type <cron|job> --name <name> [options]

Options:
  --service <name>
  --web-service <name>
  --database-service <name>
  --repo <owner/repository>
  --branch <branch>
EOF
}

die() {
  printf '%s\n' "$*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --type) TYPE="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --service) SERVICE="$2"; shift 2 ;;
    --web-service) WEB_SERVICE="$2"; shift 2 ;;
    --database-service) DATABASE_SERVICE="$2"; shift 2 ;;
    --repo) REPOSITORY="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) usage; die "Unknown option: $1" ;;
  esac
done

[[ -n "$PROJECT" && -n "$TYPE" && -n "$NAME" ]] || { usage; die "--project, --type, and --name are required"; }
[[ "$TYPE" == "cron" || "$TYPE" == "job" ]] || die "--type must be cron or job"
[[ "$NAME" =~ ^[a-z0-9][a-z0-9-]*$ ]] || die "--name must use lowercase letters, numbers, and hyphens"
command -v railway >/dev/null || die "railway CLI is required"
command -v python3 >/dev/null || die "python3 is required"

if [[ "$TYPE" == "cron" ]]; then
  DIRECTORY="cron"
else
  DIRECTORY="jobs"
fi
SERVICE="${SERVICE:-$TYPE-$NAME}"
CONFIG_FILE="/deploy/railway/production/$DIRECTORY/$NAME/railway.toml"
[[ -f "$ROOT_DIR${CONFIG_FILE}" ]] || die "Missing $CONFIG_FILE. Create and commit it before provisioning."

railway link --project "$PROJECT" --environment "$ENVIRONMENT" >/dev/null
if [[ "$(railway service list --json | python3 -c 'import json, sys; name = sys.argv[1]; print("true" if any(s["name"] == name for s in json.load(sys.stdin)) else "false")' "$SERVICE")" == "false" ]]; then
  railway add --service "$SERVICE" --json >/dev/null
fi

mapfile -t regions < <(railway service list --json | python3 -c '
import json, sys
name = sys.argv[1]
for service in json.load(sys.stdin):
    if service["name"] == name:
        print("\n".join(region["name"] for region in service.get("regions", []) if region.get("configured", 0)))
        break
' "$SERVICE")
scale=("$EU_REGION=1")
for region in "${regions[@]}"; do
  [[ -z "$region" || "$region" == "$EU_REGION" ]] || scale+=("$region=0")
done
railway service scale --project "$PROJECT" --environment "$ENVIRONMENT" --service "$SERVICE" "${scale[@]}" >/dev/null

private_domain='${{'$DATABASE_SERVICE'.RAILWAY_PRIVATE_DOMAIN}}'
database_name='${{'$DATABASE_SERVICE'.PGDATABASE}}'
database_port='${{'$DATABASE_SERVICE'.PGPORT}}'
app_password='${{'$WEB_SERVICE'.DATABASE__PASSWORD}}'
migrator_password='${{'$WEB_SERVICE'.MIGRATOR__PASSWORD}}'
jwt_secret='${{'$WEB_SERVICE'.AUTH_JWT_SECRET}}'

set_variable() {
  railway variable set "$1=$2" --project "$PROJECT" --environment "$ENVIRONMENT" --service "$SERVICE" --skip-deploys >/dev/null
}

set_variable ENV production
set_variable ENV_FILE /dev/null
set_variable YAML_CONFIG_FILE deploy/railway/production/app/config.yaml
set_variable DATABASE__HOST "$private_domain"
set_variable DATABASE__PORT "$database_port"
set_variable DATABASE__DB "$database_name"
set_variable DATABASE__PASSWORD "$app_password"
set_variable MIGRATOR__HOST "$private_domain"
set_variable MIGRATOR__PORT "$database_port"
set_variable MIGRATOR__DB "$database_name"
set_variable MIGRATOR__PASSWORD "$migrator_password"
set_variable AUTH_JWT_SECRET "$jwt_secret"

railway environment edit --project "$PROJECT" --environment "$ENVIRONMENT" --service-config "$SERVICE" configFile "$CONFIG_FILE" --message "Configure $SERVICE" >/dev/null
railway service source connect --project "$PROJECT" --environment "$ENVIRONMENT" --service "$SERVICE" --repo "$REPOSITORY" --branch "$BRANCH" >/dev/null
printf 'Provisioned %s.\n' "$SERVICE"
