#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PYRIGHT_BIN="$REPO_ROOT/node_modules/.bin/pyright"

if [[ ! -x "$PYRIGHT_BIN" ]]; then
  echo "ERROR: Missing locked Pyright installation."
  echo "Install hint: npm ci --ignore-scripts"
  exit 1
fi

changed_python_files=()
while IFS= read -r file; do
  if [[ -n "$file" && "$file" == *.py && -f "$file" ]]; then
    changed_python_files+=("$file")
  fi
done < <(
  {
    upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)"
    if [[ -n "$upstream" ]]; then
      git diff --name-only --diff-filter=ACMR "$upstream"...HEAD
    fi
    git diff --name-only --diff-filter=ACMR
    git diff --cached --name-only --diff-filter=ACMR
  } | sort -u
)

if (( ${#changed_python_files[@]} > 0 )); then
  echo "==> Pyright touched-file check"
  printf '  %s\n' "${changed_python_files[@]}"
  "$PYRIGHT_BIN" "${changed_python_files[@]}"
else
  echo "==> Pyright touched-file check (no changed Python files)"
fi

echo "==> Pyright full-project check"
"$PYRIGHT_BIN"
