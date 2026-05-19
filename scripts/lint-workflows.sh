#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Workflow lint (actionlint)"

if command -v actionlint >/dev/null 2>&1; then
  actionlint -color
  exit 0
fi

if command -v docker >/dev/null 2>&1; then
  # Use the official actionlint image when local binary is unavailable.
  docker run --rm -v "$REPO_ROOT:/repo" -w /repo rhysd/actionlint:latest -color
  exit 0
fi

echo "ERROR: actionlint is not available locally."
echo "Install hint (macOS): brew install actionlint"
echo "Alternative: install Docker and rerun this script to use rhysd/actionlint:latest"
exit 1
