#!/usr/bin/env bash
set -euo pipefail

PROJECT=""
ENVIRONMENT="production"
SERVICE=""

usage() {
  printf 'Usage: %s --project <name-or-id> --service <name> [--environment <name>]\n' "$0"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --environment) ENVIRONMENT="$2"; shift 2 ;;
    --service) SERVICE="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) usage; exit 1 ;;
  esac
done

[[ -n "$PROJECT" && -n "$SERVICE" ]] || { usage; exit 1; }
command -v railway >/dev/null || { printf '%s\n' 'railway CLI is required' >&2; exit 1; }

railway redeploy --project "$PROJECT" --environment "$ENVIRONMENT" --service "$SERVICE" --from-source --yes
