#!/usr/bin/env sh
set -eu

: "${ROOT_DATABASE_URL:?ROOT_DATABASE_URL is required}"
: "${MIGRATOR_DB_USER:?MIGRATOR_DB_USER is required}"
: "${MIGRATOR_DB_PASSWORD:?MIGRATOR_DB_PASSWORD is required}"
: "${APP_DB_USER:?APP_DB_USER is required}"
: "${APP_DB_PASSWORD:?APP_DB_PASSWORD is required}"
: "${OPENWEBUI_DB_USER:?OPENWEBUI_DB_USER is required}"
: "${OPENWEBUI_DB_PASSWORD:?OPENWEBUI_DB_PASSWORD is required}"
: "${OPENWEBUI_DB:?OPENWEBUI_DB is required}"
: "${APP_DB:?APP_DB is required}"

psql "$ROOT_DATABASE_URL" \
  -v ON_ERROR_STOP=1 \
  -v migrator_user="$MIGRATOR_DB_USER" \
  -v migrator_password="$MIGRATOR_DB_PASSWORD" \
  -v app_user="$APP_DB_USER" \
  -v app_password="$APP_DB_PASSWORD" \
  -v openwebui_user="$OPENWEBUI_DB_USER" \
  -v openwebui_password="$OPENWEBUI_DB_PASSWORD" \
  -v openwebui_db="$OPENWEBUI_DB" \
  -v app_db="$APP_DB" \
  -f /app/bootstrap.sql
