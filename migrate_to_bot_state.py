### File: migrate_to_bot_state.py
"""
One-off migration: posted_jokes.txt -> bot_state.json

Reads all entries from posted_jokes.txt and writes them into bot_state.json
under the posted_jokes key, tagging each entry with provider="icanhazdadjoke"
(all existing history came from that source).

Safe to re-run: duplicate b64 values are skipped.
Does NOT delete posted_jokes.txt — verify bot_state.json first, then delete
posted_jokes.txt and commit both changes.

Usage:
    .venv/bin/python migrate_to_bot_state.py
"""
import os
import sys

import bluesky_state

POSTED_JOKES_FILE = "posted_jokes.txt"
LEGACY_PROVIDER = "icanhazdadjoke"


def migrate():
    if not os.path.exists(POSTED_JOKES_FILE):
        print(f"{POSTED_JOKES_FILE} not found — nothing to migrate.")
        return

    state = bluesky_state.load_state()
    existing_b64s = {e["b64"] for e in state["posted_jokes"]}

    added = 0
    skipped = 0
    bad_rows = 0

    with open(POSTED_JOKES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(" ", 1)
            if len(parts) != 2:
                bad_rows += 1
                continue
            ts_str, b64 = parts
            try:
                ts = float(ts_str)
            except ValueError:
                bad_rows += 1
                continue

            if b64 in existing_b64s:
                skipped += 1
                continue

            state["posted_jokes"].append(
                {"ts": int(ts), "b64": b64, "provider": LEGACY_PROVIDER}
            )
            existing_b64s.add(b64)
            added += 1

    bluesky_state.save_state(state)

    print(f"Migration complete.")
    print(f"  Added   : {added} jokes")
    print(f"  Skipped : {skipped} duplicates")
    print(f"  Bad rows: {bad_rows} (unparseable lines ignored)")
    print(f"  Total in bot_state.json: {len(state['posted_jokes'])}")
    print()
    print(f"Next steps:")
    print(f"  1. Inspect bot_state.json to verify the migration looks correct.")
    print(f"  2. Delete {POSTED_JOKES_FILE}.")
    print(f"  3. Commit bot_state.json and the deletion of {POSTED_JOKES_FILE}.")


if __name__ == "__main__":
    migrate()
