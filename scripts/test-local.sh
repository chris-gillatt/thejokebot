#!/usr/bin/env bash
set -euo pipefail

# Run the project's local test suite with the same verbosity used in CI checks.
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
if [[ -x "$PYTHON_BIN" ]]; then
  "$PYTHON_BIN" -m pytest tests/ -v --tb=short
else
  python3 -m pytest tests/ -v --tb=short
fi
