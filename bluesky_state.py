### File: bluesky_state.py
"""
Unified runtime state for the joke bot.

Replaces posted_jokes.txt with a single JSON file (bot_state.json) that
tracks both joke history (base64-encoded, for deduplication) and provider
rotation/failure state.

Writes are performed atomically via a temp file + os.replace() to prevent
corruption if a run is interrupted.
"""
import json
import os
import time

STATE_FILE = "bot_state.json"

# Canonical provider order — the rotation wraps around this list.
# Add new providers here and they will be included in rotation automatically.
PROVIDER_ROTATION_ORDER = ["icanhazdadjoke", "jokeapi"]


def _default_state() -> dict:
    return {
        "provider": {
            "last_used": None,
            "last_used_at": None,
            "rotation_order": list(PROVIDER_ROTATION_ORDER),
            "failures": {
                p: {"count": 0, "last_failure_at": None, "last_error": None}
                for p in PROVIDER_ROTATION_ORDER
            },
        },
        "posted_jokes": [],
    }


def load_state() -> dict:
    """Load state from disk. Returns a fresh default state if the file is missing or corrupt."""
    if not os.path.exists(STATE_FILE):
        return _default_state()
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        print(f"Warning: could not read {STATE_FILE}; starting with empty state.")
        return _default_state()


def save_state(state: dict) -> None:
    """Write state to disk atomically."""
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)


def get_next_provider(state: dict, override: str | None = None) -> str:
    """
    Return the provider name to use for this run.

    - override: explicit provider name (from BLUESKY_JOKE_PROVIDER env var).
                Ignored if the value is not in the rotation list.
    - None / empty: pick the next provider in rotation (alternating, wraps around).
                    Scales naturally as new providers are added to rotation_order.
    """
    rotation = state["provider"].get("rotation_order") or PROVIDER_ROTATION_ORDER

    if override and override in rotation:
        return override

    last = state["provider"].get("last_used")
    if last is None or last not in rotation:
        return rotation[0]

    idx = rotation.index(last)
    return rotation[(idx + 1) % len(rotation)]


def record_provider_used(state: dict, provider: str) -> None:
    """Advance the rotation by recording which provider was used this run."""
    state["provider"]["last_used"] = provider
    state["provider"]["last_used_at"] = int(time.time())


def record_failure(state: dict, provider: str, error: str) -> None:
    """Increment the failure counter for a provider."""
    failures = state["provider"].setdefault("failures", {})
    entry = failures.setdefault(
        provider, {"count": 0, "last_failure_at": None, "last_error": None}
    )
    entry["count"] += 1
    entry["last_failure_at"] = int(time.time())
    entry["last_error"] = str(error)


def add_posted_joke(state: dict, b64: str, provider: str) -> None:
    """Record a successfully posted joke in state."""
    state["posted_jokes"].append(
        {"ts": int(time.time()), "b64": b64, "provider": provider}
    )


def get_recent_b64s(state: dict, cutoff_ts: float) -> set:
    """Return the set of base64-encoded jokes posted after cutoff_ts."""
    return {e["b64"] for e in state["posted_jokes"] if e["ts"] > cutoff_ts}


def prune_old_jokes(state: dict, cutoff_ts: float) -> None:
    """Remove joke history entries older than cutoff_ts."""
    state["posted_jokes"] = [
        e for e in state["posted_jokes"] if e["ts"] > cutoff_ts
    ]
