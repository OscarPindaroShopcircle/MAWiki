#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PROJECT=""
ENVIRONMENT="production"
SECRETS_FILE="$ROOT_DIR/deploy/railway/production/.env"
WEB_SERVICE="MAWiki"
DATABASE_SERVICE="Postgres"
OPEN_WEBUI_SERVICE="Open WebUI"
BOOTSTRAP_SERVICE="database-bootstrap"
REPOSITORY="OscarPindaroShopcircle/MAWiki"
BRANCH="main"
MIGRATE_REGION=false
EU_REGION="europe-west4-drams3a"

declare -A SECRETS

usage() {
  cat <<EOF
Usage: $0 --project <name-or-id> [options]

Options:
  --secrets-file <path>      Defaults to deploy/railway/production/.env
  --web-service <name>       Defaults to MAWiki
  --database-service <name>  Defaults to Postgres
  --open-webui-service <name>
                              Defaults to Open WebUI
  --bootstrap-service <name> Defaults to database-bootstrap
  --repo <owner/repository>  Defaults to OscarPindaroShopcircle/MAWiki
  --branch <branch>          Defaults to main
  --migrate-region           Move existing services and attached volumes to EU West
EOF
}

die() {
  printf '%s\n' "$*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --secrets-file) SECRETS_FILE="$2"; shift 2 ;;
    --web-service) WEB_SERVICE="$2"; shift 2 ;;
    --database-service) DATABASE_SERVICE="$2"; shift 2 ;;
    --open-webui-service) OPEN_WEBUI_SERVICE="$2"; shift 2 ;;
    --bootstrap-service) BOOTSTRAP_SERVICE="$2"; shift 2 ;;
    --repo) REPOSITORY="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --migrate-region) MIGRATE_REGION=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) usage; die "Unknown option: $1" ;;
  esac
done

[[ -n "$PROJECT" ]] || { usage; die "--project is required"; }
command -v railway >/dev/null || die "railway CLI is required"
command -v python3 >/dev/null || die "python3 is required"
[[ -f "$SECRETS_FILE" ]] || die "Secrets file not found: $SECRETS_FILE"

load_secrets() {
  local line key value
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" == *=* ]] || die "Invalid secrets-file line: $line"
    key="${line%%=*}"
    value="${line#*=}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "Invalid variable name: $key"
    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi
    SECRETS["$key"]="$value"
  done < "$SECRETS_FILE"
}

require_secret() {
  [[ -n "${SECRETS[$1]:-}" ]] || die "$1 must be set in $SECRETS_FILE"
}

service_exists() {
  railway service list --json | python3 -c '
import json, sys
name = sys.argv[1]
print("true" if any(service["name"] == name for service in json.load(sys.stdin)) else "false")
' "$1"
}

service_regions() {
  railway service list --json | python3 -c '
import json, sys
name = sys.argv[1]
for service in json.load(sys.stdin):
    if service["name"] == name:
        print("\n".join(region["name"] for region in service.get("regions", []) if region.get("configured", 0)))
        break
' "$1"
}

service_url() {
  railway service list --json | python3 -c '
import json, sys
name = sys.argv[1]
for service in json.load(sys.stdin):
    if service["name"] == name:
        print(service.get("url") or "")
        break
' "$1"
}

ensure_service() {
  local service="$1"
  if [[ "$(service_exists "$service")" == "false" ]]; then
    printf 'Creating service %s\n' "$service"
    railway add --service "$service" --json >/dev/null
  fi
}

ensure_database() {
  if [[ "$(service_exists "$DATABASE_SERVICE")" == "true" ]]; then
    return
  fi
  [[ "$DATABASE_SERVICE" == "Postgres" ]] || die "Railway names a newly added PostgreSQL service Postgres; use --database-service Postgres"
  printf 'Creating PostgreSQL service\n'
  railway add --database postgres --json >/dev/null
}

ensure_eu_region() {
  local service="$1" existed="$2" region
  local -a regions=("$EU_REGION=1")
  if [[ "$existed" == "true" && "$MIGRATE_REGION" != true ]]; then
    while IFS= read -r region; do
      [[ -z "$region" || "$region" == "$EU_REGION" ]] || die "$service is in $region. Re-run with --migrate-region to move it to EU West."
    done < <(service_regions "$service")
    return
  fi
  while IFS= read -r region; do
    [[ -z "$region" || "$region" == "$EU_REGION" ]] || regions+=("$region=0")
  done < <(service_regions "$service")
  railway service scale --project "$PROJECT" --environment "$ENVIRONMENT" --service "$service" "${regions[@]}" >/dev/null
}

wait_for_eu_region() {
  local service="$1" ready
  for _ in {1..120}; do
    ready="$(railway service list --json | python3 -c '
import json, sys
name, region = sys.argv[1:]
for service in json.load(sys.stdin):
    if service["name"] == name:
        regions = {item["name"] for item in service.get("regions", []) if item.get("configured", 0)}
        print("true" if regions == {region} and not service.get("volumeMigrating", False) else "false")
        break
else:
    print("false")
' "$service" "$EU_REGION")"
    [[ "$ready" == "true" ]] && return
    sleep 5
  done
  die "Timed out moving $service to EU West"
}

ensure_volume() {
  local service="$1" mount_path="$2"
  if railway service list --json | python3 -c '
import json, sys
service_name, mount_path = sys.argv[1:]
for service in json.load(sys.stdin):
    if service["name"] == service_name:
        raise SystemExit(0 if any(volume.get("mountPath") == mount_path for volume in service.get("volumes", [])) else 1)
raise SystemExit(1)
' "$service" "$mount_path"; then
    return
  fi
  railway volume add --project "$PROJECT" --environment "$ENVIRONMENT" --service "$service" --mount-path "$mount_path" --json >/dev/null
}

ensure_domain() {
  local service="$1" port="$2" url
  url="$(service_url "$service")"
  if [[ -n "$url" ]]; then
    printf '%s' "$url"
    return
  fi
  railway domain --project "$PROJECT" --environment "$ENVIRONMENT" --service "$service" --port "$port" --json >/dev/null
  for _ in {1..12}; do
    url="$(service_url "$service")"
    if [[ -n "$url" ]]; then
      printf '%s' "$url"
      return
    fi
    sleep 2
  done
  die "Railway did not provide a domain for $service"
}

set_variable() {
  railway variable set "$1=$2" --project "$PROJECT" --environment "$ENVIRONMENT" --service "$3" --skip-deploys >/dev/null
}

set_config_file() {
  railway environment edit --project "$PROJECT" --environment "$ENVIRONMENT" --service-config "$1" configFile "$2" --message "Configure $1" >/dev/null
}

connect_source() {
  railway service source connect --project "$PROJECT" --environment "$ENVIRONMENT" --service "$1" --repo "$REPOSITORY" --branch "$BRANCH" >/dev/null
}

wait_for_deployment() {
  local service="$1" status
  for _ in {1..120}; do
    status="$(railway deployment list --project "$PROJECT" --environment "$ENVIRONMENT" --service "$service" --limit 1 --json | python3 -c 'import json, sys; deployments = json.load(sys.stdin); print(deployments[0]["status"] if deployments else "")')"
    case "$status" in
      SUCCESS) return ;;
      FAILED|CRASHED|CANCELED|REMOVED)
        railway service logs --project "$PROJECT" --environment "$ENVIRONMENT" --service "$service" --lines 200 >&2 || true
        die "$service deployment finished with $status"
        ;;
    esac
    sleep 5
  done
  die "Timed out waiting for $service"
}

load_secrets
for key in DATABASE__PASSWORD MIGRATOR__PASSWORD OPENWEBUI__PASSWORD AUTH_JWT_SECRET AUTH__BOOTSTRAP_ADMIN_EMAIL WEBUI_SECRET_KEY WEBUI_ADMIN_EMAIL WEBUI_ADMIN_PASSWORD ANTHROPIC_API_KEY; do
  require_secret "$key"
done

railway link --project "$PROJECT" --environment "$ENVIRONMENT" >/dev/null

web_existed="$(service_exists "$WEB_SERVICE")"
database_existed="$(service_exists "$DATABASE_SERVICE")"
bootstrap_existed="$(service_exists "$BOOTSTRAP_SERVICE")"
open_webui_existed="$(service_exists "$OPEN_WEBUI_SERVICE")"

if [[ "$web_existed" == "true" ]]; then
  ensure_eu_region "$WEB_SERVICE" true
fi
if [[ "$database_existed" == "true" ]]; then
  ensure_eu_region "$DATABASE_SERVICE" true
fi
if [[ "$bootstrap_existed" == "true" ]]; then
  ensure_eu_region "$BOOTSTRAP_SERVICE" true
fi
if [[ "$open_webui_existed" == "true" ]]; then
  ensure_eu_region "$OPEN_WEBUI_SERVICE" true
fi

ensure_database
ensure_service "$WEB_SERVICE"
ensure_service "$BOOTSTRAP_SERVICE"
ensure_service "$OPEN_WEBUI_SERVICE"

if [[ "$web_existed" == "false" ]]; then
  ensure_eu_region "$WEB_SERVICE" false
fi
if [[ "$database_existed" == "false" ]]; then
  ensure_eu_region "$DATABASE_SERVICE" false
fi
if [[ "$bootstrap_existed" == "false" ]]; then
  ensure_eu_region "$BOOTSTRAP_SERVICE" false
fi
if [[ "$open_webui_existed" == "false" ]]; then
  ensure_eu_region "$OPEN_WEBUI_SERVICE" false
fi
wait_for_eu_region "$DATABASE_SERVICE"
ensure_volume "$WEB_SERVICE" /data
ensure_volume "$OPEN_WEBUI_SERVICE" /app/backend/data

web_url="${SECRETS[WEB_PUBLIC_URL]:-$(ensure_domain "$WEB_SERVICE" 8000)}"
open_webui_url="${SECRETS[OPEN_WEBUI_PUBLIC_URL]:-$(ensure_domain "$OPEN_WEBUI_SERVICE" 8080)}"
private_domain='${{'$DATABASE_SERVICE'.RAILWAY_PRIVATE_DOMAIN}}'
database_name='${{'$DATABASE_SERVICE'.PGDATABASE}}'
database_port='${{'$DATABASE_SERVICE'.PGPORT}}'
root_database_url='${{'$DATABASE_SERVICE'.DATABASE_URL}}'

set_variable ROOT_DATABASE_URL "$root_database_url" "$BOOTSTRAP_SERVICE"
set_variable MIGRATOR_DB_USER migrator_user "$BOOTSTRAP_SERVICE"
set_variable MIGRATOR_DB_PASSWORD "${SECRETS[MIGRATOR__PASSWORD]}" "$BOOTSTRAP_SERVICE"
set_variable APP_DB_USER app_user "$BOOTSTRAP_SERVICE"
set_variable APP_DB_PASSWORD "${SECRETS[DATABASE__PASSWORD]}" "$BOOTSTRAP_SERVICE"
set_variable OPENWEBUI_DB_USER openwebui_user "$BOOTSTRAP_SERVICE"
set_variable OPENWEBUI_DB_PASSWORD "${SECRETS[OPENWEBUI__PASSWORD]}" "$BOOTSTRAP_SERVICE"
set_variable OPENWEBUI_DB openwebui "$BOOTSTRAP_SERVICE"
set_variable APP_DB "$database_name" "$BOOTSTRAP_SERVICE"

set_variable ENV production "$WEB_SERVICE"
set_variable ENV_FILE /dev/null "$WEB_SERVICE"
set_variable YAML_CONFIG_FILE deploy/railway/production/app/config.yaml "$WEB_SERVICE"
set_variable DATABASE__HOST "$private_domain" "$WEB_SERVICE"
set_variable DATABASE__PORT "$database_port" "$WEB_SERVICE"
set_variable DATABASE__DB "$database_name" "$WEB_SERVICE"
set_variable DATABASE__PASSWORD "${SECRETS[DATABASE__PASSWORD]}" "$WEB_SERVICE"
set_variable MIGRATOR__HOST "$private_domain" "$WEB_SERVICE"
set_variable MIGRATOR__PORT "$database_port" "$WEB_SERVICE"
set_variable MIGRATOR__DB "$database_name" "$WEB_SERVICE"
set_variable MIGRATOR__PASSWORD "${SECRETS[MIGRATOR__PASSWORD]}" "$WEB_SERVICE"
set_variable AUTH_JWT_SECRET "${SECRETS[AUTH_JWT_SECRET]}" "$WEB_SERVICE"
set_variable AUTH__BOOTSTRAP_ADMIN_EMAIL "${SECRETS[AUTH__BOOTSTRAP_ADMIN_EMAIL]}" "$WEB_SERVICE"
set_variable AUTH__REDIRECT_URI "${web_url%/}/auth/callback" "$WEB_SERVICE"
set_variable CORS_ORIGINS "[\"$web_url\"]" "$WEB_SERVICE"

set_variable ENV production "$OPEN_WEBUI_SERVICE"
set_variable DATABASE_URL "postgresql://openwebui_user:${SECRETS[OPENWEBUI__PASSWORD]}@$private_domain:$database_port/openwebui" "$OPEN_WEBUI_SERVICE"
set_variable WEBUI_URL "$open_webui_url" "$OPEN_WEBUI_SERVICE"
set_variable WEBUI_SECRET_KEY "${SECRETS[WEBUI_SECRET_KEY]}" "$OPEN_WEBUI_SERVICE"
set_variable WEBUI_ADMIN_EMAIL "${SECRETS[WEBUI_ADMIN_EMAIL]}" "$OPEN_WEBUI_SERVICE"
set_variable WEBUI_ADMIN_PASSWORD "${SECRETS[WEBUI_ADMIN_PASSWORD]}" "$OPEN_WEBUI_SERVICE"
set_variable ENABLE_PERSISTENT_CONFIG False "$OPEN_WEBUI_SERVICE"
set_variable CORS_ALLOW_ORIGIN "$open_webui_url" "$OPEN_WEBUI_SERVICE"
set_variable WEBUI_NAME Menelao "$OPEN_WEBUI_SERVICE"
set_variable DEFAULT_USER_ROLE user "$OPEN_WEBUI_SERVICE"
set_variable ENABLE_OLLAMA_API False "$OPEN_WEBUI_SERVICE"
set_variable ENABLE_OPENAI_API True "$OPEN_WEBUI_SERVICE"
set_variable ENABLE_IMAGE_GENERATION False "$OPEN_WEBUI_SERVICE"
set_variable ENABLE_CODE_INTERPRETER False "$OPEN_WEBUI_SERVICE"
set_variable ENABLE_CODE_EXECUTION False "$OPEN_WEBUI_SERVICE"
set_variable ENABLE_AUTOCOMPLETE_GENERATION False "$OPEN_WEBUI_SERVICE"
set_variable ENABLE_FOLLOW_UP_GENERATION False "$OPEN_WEBUI_SERVICE"
set_variable ENABLE_RAG_WEB_SEARCH False "$OPEN_WEBUI_SERVICE"
set_variable OPENAI_API_BASE_URLS https://api.anthropic.com/v1 "$OPEN_WEBUI_SERVICE"
set_variable OPENAI_API_KEYS "${SECRETS[ANTHROPIC_API_KEY]}" "$OPEN_WEBUI_SERVICE"

set_config_file "$BOOTSTRAP_SERVICE" /deploy/railway/production/database-bootstrap/railway.toml
set_config_file "$WEB_SERVICE" /deploy/railway/production/app/railway.toml
set_config_file "$OPEN_WEBUI_SERVICE" /deploy/railway/production/open-webui/railway.toml

connect_source "$BOOTSTRAP_SERVICE"
wait_for_deployment "$BOOTSTRAP_SERVICE"
connect_source "$WEB_SERVICE"
connect_source "$OPEN_WEBUI_SERVICE"
wait_for_deployment "$WEB_SERVICE"
wait_for_deployment "$OPEN_WEBUI_SERVICE"

printf 'Menelao web: %s\nOpen WebUI: %s\n' "$web_url" "$open_webui_url"
