#!/usr/bin/env bash
set -euo pipefail

# Local quality gate to run before commit/push.
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

MISSING_OPTIONAL=()

fail_with_install_hint() {
  local dependency="$1"
  local install_hint="$2"
  echo "ERROR: Missing dependency: ${dependency}"
  echo "Install hint: ${install_hint}"
  exit 1
}

PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
if [[ -x "$PYTHON_BIN" ]]; then
  PYTHON=("$PYTHON_BIN")
elif command -v python3 >/dev/null 2>&1; then
  PYTHON=(python3)
else
  fail_with_install_hint "python3" "brew install python"
fi

# Required modules for preflight. If these are missing, fail with a direct
# install hint so local validation is not silently weakened.
if ! "${PYTHON[@]}" -m ruff --version >/dev/null 2>&1; then
  fail_with_install_hint "ruff (Python module)" "${PYTHON[*]} -m pip install ruff"
fi

if ! "${PYTHON[@]}" -m pytest --version >/dev/null 2>&1; then
  fail_with_install_hint "pytest (Python module)" "${PYTHON[*]} -m pip install pytest"
fi

echo "==> Ruff lint"
"${PYTHON[@]}" -m ruff check .

echo "==> Ruff format check"
"${PYTHON[@]}" -m ruff format --check .

echo "==> Unit tests"
"${PYTHON[@]}" -m pytest tests/ -v --tb=short

if command -v codeql >/dev/null 2>&1; then
  CODEQL_TMP="$REPO_ROOT/.agent-tmp/codeql-local"
  CODEQL_SUITE="codeql/python-queries:codeql-suites/python-security-and-quality.qls"
  mkdir -p "$CODEQL_TMP"

  echo "==> CodeQL query pack check"
  if ! codeql resolve queries "$CODEQL_SUITE" >/dev/null 2>&1; then
    echo "CodeQL query pack missing locally; attempting download..."
    if ! codeql pack download codeql/python-queries; then
      fail_with_install_hint \
        "CodeQL Python query pack" \
        "codeql pack download codeql/python-queries"
    fi
  fi

  echo "==> CodeQL database create"
  codeql database create "$CODEQL_TMP/db" \
    --language=python \
    --source-root "$REPO_ROOT" \
    --overwrite

  echo "==> CodeQL analyse (python-security-and-quality)"
  codeql database analyze "$CODEQL_TMP/db" \
    "$CODEQL_SUITE" \
    --format=sarif-latest \
    --output "$CODEQL_TMP/results.sarif"

  echo "CodeQL SARIF written to: $CODEQL_TMP/results.sarif"
else
  MISSING_OPTIONAL+=("codeql")
  echo "WARNING: Optional dependency missing: codeql"
  echo "Install hint: brew install codeql"
  echo "CodeQL checks were skipped, so local coverage is reduced."
fi

if [[ "${#MISSING_OPTIONAL[@]}" -gt 0 ]]; then
  echo "Local preflight checks passed with reduced coverage."
  echo "Missing optional dependencies: ${MISSING_OPTIONAL[*]}"
else
  echo "Local preflight checks passed with full coverage."
fi
