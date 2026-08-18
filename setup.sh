#!/usr/bin/env bash
set -euo pipefail

HARNESS=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --harness) HARNESS=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

VENV_PATH=".venv"
if [ -z "${VIRTUAL_ENV:-}" ]; then
    source "$VENV_PATH/bin/activate"
fi

uv sync --dev
uv run pre-commit install

if [ "$HARNESS" = true ]; then
    echo ""
    echo "Installing harness MCP servers..."
    uv run menelao harness install --agent all --yes
fi
