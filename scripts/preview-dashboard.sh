#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${DASHBOARD_PREVIEW_PORT:-8765}"

if [[ ! "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1 || PORT > 65535 )); then
  echo "ERROR: DASHBOARD_PREVIEW_PORT must be an integer between 1 and 65535." >&2
  exit 1
fi

"$REPO_ROOT/scripts/prepare-dashboard-pages.sh"

PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "ERROR: python3 is required to preview the dashboard." >&2
  exit 1
fi

echo "Dashboard preview: http://localhost:$PORT/"
exec "$PYTHON_BIN" -m http.server "$PORT" --bind localhost --directory "$REPO_ROOT/.agent-tmp/pages"