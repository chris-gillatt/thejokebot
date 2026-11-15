#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Workflow lint (actionlint)"

python3 scripts/check_action_pins.py

if command -v actionlint >/dev/null 2>&1; then
  python3 scripts/lint_action_workflows.py
  exit 0
fi

if command -v docker >/dev/null 2>&1; then
  # Use the official actionlint image when local binary is unavailable.
  python3 scripts/lint_action_workflows.py --docker
  exit 0
fi

echo "ERROR: actionlint is not available locally."
echo "Install hint (macOS): brew install actionlint"
echo "Alternative: install Docker and rerun this script to use rhysd/actionlint:latest"
exit 1
