#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PYRIGHT_VERSION="1.1.413"

if ! command -v npx >/dev/null 2>&1; then
  echo "ERROR: Missing dependency: npx"
  echo "Install hint: brew install node"
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
  npx --yes "pyright@${PYRIGHT_VERSION}" "${changed_python_files[@]}"
else
  echo "==> Pyright touched-file check (no changed Python files)"
fi

echo "==> Pyright full-project check"
npx --yes "pyright@${PYRIGHT_VERSION}"
