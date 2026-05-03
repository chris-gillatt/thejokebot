#!/usr/bin/env bash
set -euo pipefail

# Local quality gate to run before commit/push.
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
if [[ -x "$PYTHON_BIN" ]]; then
  PYTHON=("$PYTHON_BIN")
else
  PYTHON=(python3)
fi

echo "==> Ruff lint"
"${PYTHON[@]}" -m ruff check .

echo "==> Ruff format check"
"${PYTHON[@]}" -m ruff format --check .

echo "==> Unit tests"
"${PYTHON[@]}" -m pytest tests/ -v --tb=short

if command -v codeql >/dev/null 2>&1; then
  CODEQL_TMP="$REPO_ROOT/.agent-tmp/codeql-local"
  mkdir -p "$CODEQL_TMP"

  echo "==> CodeQL database create"
  codeql database create "$CODEQL_TMP/db" \
    --language=python \
    --source-root "$REPO_ROOT" \
    --overwrite

  echo "==> CodeQL analyse (python-security-and-quality)"
  codeql database analyze "$CODEQL_TMP/db" \
    codeql/python-queries:codeql-suites/python-security-and-quality.qls \
    --format=sarif-latest \
    --output "$CODEQL_TMP/results.sarif"

  echo "CodeQL SARIF written to: $CODEQL_TMP/results.sarif"
else
  echo "==> CodeQL skipped (codeql CLI not found on PATH)"
  echo "Install CodeQL CLI to enable local security analysis parity with CI."
fi

echo "Local preflight checks passed."
