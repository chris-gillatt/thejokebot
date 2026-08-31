#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGING_DIR="$REPO_ROOT/.agent-tmp/pages"

required_files=(
  "$REPO_ROOT/dashboard/index.html"
  "$REPO_ROOT/dashboard/app.js"
  "$REPO_ROOT/dashboard/styles.css"
  "$REPO_ROOT/dashboard/data/metrics.json"
  "$REPO_ROOT/images/jokebot_cover.png"
  "$REPO_ROOT/images/jokebot_logo.webp"
)

for required_file in "${required_files[@]}"; do
  if [[ ! -f "$required_file" ]]; then
    echo "ERROR: Required dashboard file is missing: $required_file" >&2
    exit 1
  fi
done

rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR/images"
cp -R "$REPO_ROOT/dashboard/." "$STAGING_DIR/"
cp "$REPO_ROOT/images/jokebot_cover.png" "$STAGING_DIR/images/jokebot_cover.png"
cp "$REPO_ROOT/images/jokebot_logo.webp" "$STAGING_DIR/images/jokebot_logo.webp"
touch "$STAGING_DIR/.nojekyll"

echo "Dashboard Pages artifact prepared at $STAGING_DIR"