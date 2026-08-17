#!/usr/bin/env bash
set -euo pipefail

ENCRYPTED_PATH="${BLUESKY_SESSION_ENCRYPTED_PATH:-.agent-tmp/bluesky_session.txt.enc}"
SESSION_PATH="${BLUESKY_SESSION_FILE_PATH:-.agent-tmp/bluesky_session.txt}"

rm -f "$SESSION_PATH"
if [[ ! -s "$ENCRYPTED_PATH" ]]; then
  echo "No encrypted Bluesky session cache was restored."
  exit 0
fi

: "${BLUESKY_SESSION_CACHE_KEY:?BLUESKY_SESSION_CACHE_KEY is required to restore the session cache}"

mkdir -p "$(dirname "$SESSION_PATH")"
umask 077
if ! openssl enc -d -aes-256-cbc -pbkdf2 \
  -in "$ENCRYPTED_PATH" \
  -out "$SESSION_PATH" \
  -pass env:BLUESKY_SESSION_CACHE_KEY; then
  rm -f "$SESSION_PATH"
  echo "ERROR: Failed to decrypt the Bluesky session cache." >&2
  exit 1
fi

chmod 600 "$SESSION_PATH"
echo "Encrypted Bluesky session cache restored."