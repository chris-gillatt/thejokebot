#!/usr/bin/env bash
set -euo pipefail

ENCRYPTED_PATH="${BLUESKY_SESSION_ENCRYPTED_PATH:-.agent-tmp/bluesky_session.txt.enc}"
SESSION_PATH="${BLUESKY_SESSION_FILE_PATH:-.agent-tmp/bluesky_session.txt}"
TEMP_PATH="${ENCRYPTED_PATH}.tmp"

rm -f "$ENCRYPTED_PATH" "$TEMP_PATH"
if [[ ! -s "$SESSION_PATH" ]]; then
  rm -f "$SESSION_PATH"
  echo "No valid Bluesky session is available to cache."
  exit 0
fi

: "${BLUESKY_SESSION_CACHE_KEY:?BLUESKY_SESSION_CACHE_KEY is required to prepare the session cache}"

trap 'rm -f "$SESSION_PATH" "$TEMP_PATH"' EXIT
umask 077
openssl enc -aes-256-cbc -pbkdf2 -salt \
  -in "$SESSION_PATH" \
  -out "$TEMP_PATH" \
  -pass env:BLUESKY_SESSION_CACHE_KEY
chmod 600 "$TEMP_PATH"
mv "$TEMP_PATH" "$ENCRYPTED_PATH"
echo "Bluesky session prepared for encrypted cache storage."