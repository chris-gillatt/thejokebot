"""Repository-backed denylist helpers for joke suppression."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

DENYLIST_FILE = Path(__file__).resolve().parent / "resources" / "joke_denylist.json"


def _default_payload() -> dict:
    return {
        "version": 1,
        "jokes": [],
    }


def load_denylist(file_path: Path | None = None) -> dict:
    """Load denylist payload from disk, falling back to an empty payload."""
    path = file_path or DENYLIST_FILE
    if not path.exists():
        return _default_payload()

    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, dict):
        return _default_payload()

    payload.setdefault("version", 1)
    payload.setdefault("jokes", [])
    return payload


def save_denylist(payload: dict, file_path: Path | None = None) -> None:
    """Write denylist payload atomically."""
    path = file_path or DENYLIST_FILE
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def get_denylisted_b64s(payload: dict) -> set[str]:
    """Return a set of denylisted base64-encoded joke values."""
    jokes = payload.get("jokes", [])
    return {entry.get("b64") for entry in jokes if entry.get("b64")}


def has_b64(payload: dict, b64: str) -> bool:
    """Return True when b64 already exists in denylist payload."""
    return b64 in get_denylisted_b64s(payload)


def add_denylist_entry(
    payload: dict,
    *,
    b64: str,
    source_post_uri: str,
    source_reply_uri: str,
    reporter_did: str,
    reason: str = "user_reply_report",
) -> bool:
    """Append a denylist entry if absent. Returns True when entry was added."""
    if has_b64(payload, b64):
        return False

    payload.setdefault("jokes", []).append(
        {
            "b64": b64,
            "reason": reason,
            "first_reported_at": int(time.time()),
            "source_post_uri": source_post_uri,
            "source_reply_uri": source_reply_uri,
            "reporter_did": reporter_did,
        }
    )
    return True
