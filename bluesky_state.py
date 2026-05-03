"""
Unified runtime state for the joke bot.

Replaces posted_jokes.txt with a single JSON file (bot_state.json) that
tracks both joke history (base64-encoded, for deduplication) and provider
rotation/failure state.

Writes are performed atomically via a temp file + os.replace() to prevent
corruption if a run is interrupted. File-level locking prevents concurrent
mutations when two processes run simultaneously.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

# File locking support (Unix-like systems)
if sys.platform != "win32":
    import fcntl
else:
    fcntl = None  # type: ignore

STATE_FILE = str(Path(__file__).resolve().parent / "bot_state.json")
FOLLOW_RESPONSE_GRACE_PERIOD_DAYS = 90
FOLLOW_RESPONSE_GRACE_PERIOD_SECONDS = FOLLOW_RESPONSE_GRACE_PERIOD_DAYS * 24 * 60 * 60

# Canonical provider order — the rotation wraps around this list.
# Add new providers here and they will be included in rotation automatically.
PROVIDER_ROTATION_ORDER = ["icanhazdadjoke", "jokeapi", "groandeck"]


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
        "reports": {
            "processed_notification_uris": [],
            "last_checked_at": None,
            "deleted_post_uris": [],
            "acknowledged_report_uris": [],
        },
        "liked_replies": {
            "liked_uris": [],
            "last_checked_at": None,
        },
        "unfollow_history": {
            "entries": [],
        },
        "follow_grace": {
            "entries": [],
        },
        "follow_fellows": {
            "tag_offset": 0,
        },
        "posted_jokes": [],
    }


def _normalise_state(state: dict) -> dict:
    """Backfill missing keys for older state files."""
    defaults = _default_state()

    if not isinstance(state, dict):
        return defaults

    # Ensure required top-level sections exist.
    for key, value in defaults.items():
        if key not in state:
            state[key] = value

    provider = state.setdefault("provider", {})
    default_provider = defaults["provider"]
    for key, value in default_provider.items():
        if key not in provider:
            provider[key] = value

    # Sync rotation_order if it has changed (e.g., when new providers are added).
    saved_rotation = provider.get("rotation_order")
    if saved_rotation != PROVIDER_ROTATION_ORDER:
        provider["rotation_order"] = list(PROVIDER_ROTATION_ORDER)

    failures = provider.setdefault("failures", {})
    for provider_name in provider.get("rotation_order") or PROVIDER_ROTATION_ORDER:
        failures.setdefault(
            provider_name,
            {"count": 0, "last_failure_at": None, "last_error": None},
        )

    reports = state.setdefault("reports", {})
    reports.setdefault("processed_notification_uris", [])
    reports.setdefault("last_checked_at", None)
    reports.setdefault("deleted_post_uris", [])
    reports.setdefault("acknowledged_report_uris", [])

    liked_replies = state.setdefault("liked_replies", {})
    liked_replies.setdefault("liked_uris", [])
    liked_replies.setdefault("last_checked_at", None)

    unfollow_history = state.setdefault("unfollow_history", {})
    unfollow_history.setdefault("entries", [])

    follow_grace = state.setdefault("follow_grace", {})
    follow_grace.setdefault("entries", [])

    follow_fellows_state = state.setdefault("follow_fellows", {})
    follow_fellows_state.setdefault("tag_offset", 0)

    state.setdefault("posted_jokes", [])
    return state


def load_state() -> dict:
    """
    Load state from disk with shared lock to prevent reading mid-write.

    Returns a fresh default state if the file is missing or corrupt.
    Uses fcntl.flock() on Unix-like systems to ensure read consistency.
    """
    if not os.path.exists(STATE_FILE):
        return _default_state()

    # On Unix-like systems, acquire shared lock to prevent reading during writes.
    lock_file = None
    if fcntl is not None:
        try:
            lock_file = open(STATE_FILE + ".lock", "w", encoding="utf-8")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
        except (OSError, IOError) as e:
            print(f"Warning: could not acquire read lock on {STATE_FILE}: {e}")
            if lock_file:
                lock_file.close()
            lock_file = None

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return _normalise_state(json.load(f))
    except (json.JSONDecodeError, IOError):
        print(f"Warning: could not read {STATE_FILE}; starting with empty state.")
        return _default_state()
    finally:
        if lock_file is not None:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
            except (OSError, IOError) as e:
                print(f"Warning: could not release read lock on {STATE_FILE}: {e}")


def save_state(state: dict) -> None:
    """
    Write state to disk atomically with file-level locking to prevent concurrent mutations.

    Uses fcntl.flock() on Unix-like systems (macOS, Linux) to ensure exclusive access
    during read-modify-write operations. On Windows, relies on atomic os.replace().
    """
    # On Unix-like systems, acquire exclusive lock before writing.
    lock_file = None
    if fcntl is not None:
        try:
            lock_file = open(STATE_FILE + ".lock", "w", encoding="utf-8")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        except (OSError, IOError) as e:
            print(f"Warning: could not acquire lock on {STATE_FILE}: {e}")
            if lock_file:
                lock_file.close()
            lock_file = None

    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, STATE_FILE)
    finally:
        if lock_file is not None:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
            except (OSError, IOError) as e:
                print(f"Warning: could not release lock on {STATE_FILE}: {e}")


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


def add_posted_joke(
    state: dict,
    b64: str,
    provider: str,
    post_uri: str | None = None,
    post_cid: str | None = None,
) -> None:
    """Record a successfully posted joke in state."""
    entry = {"ts": int(time.time()), "b64": b64, "provider": provider}
    if post_uri:
        entry["post_uri"] = post_uri
    if post_cid:
        entry["post_cid"] = post_cid
    state["posted_jokes"].append(entry)


def get_recent_b64s(state: dict, cutoff_ts: float) -> set:
    """Return the set of base64-encoded jokes posted after cutoff_ts."""
    return {e["b64"] for e in state["posted_jokes"] if e["ts"] > cutoff_ts}


def prune_old_jokes(state: dict, cutoff_ts: float) -> None:
    """Remove joke history entries older than cutoff_ts."""
    state["posted_jokes"] = [e for e in state["posted_jokes"] if e["ts"] > cutoff_ts]


def get_post_uri_index(state: dict) -> dict:
    """Map post URI to posted_jokes entry for report lookup."""
    index = {}
    for entry in state.get("posted_jokes", []):
        post_uri = entry.get("post_uri")
        if post_uri:
            index[post_uri] = entry
    return index


def get_processed_notification_uris(state: dict) -> set[str]:
    """Return processed notification URIs for idempotent report ingestion."""
    reports = state.setdefault("reports", {})
    uris = reports.setdefault("processed_notification_uris", [])
    return set(uris)


def record_processed_notification(state: dict, notification_uri: str) -> None:
    """Record a processed notification URI if it has not been seen before."""
    reports = state.setdefault("reports", {})
    uris = reports.setdefault("processed_notification_uris", [])
    if notification_uri and notification_uri not in uris:
        uris.append(notification_uri)


def prune_processed_notifications(state: dict, max_entries: int = 5000) -> None:
    """Keep only the most recent processed notification URIs."""
    reports = state.setdefault("reports", {})
    uris = reports.setdefault("processed_notification_uris", [])
    if len(uris) > max_entries:
        reports["processed_notification_uris"] = uris[-max_entries:]


def set_reports_checked_now(state: dict) -> None:
    """Set the report polling timestamp to current epoch."""
    reports = state.setdefault("reports", {})
    reports["last_checked_at"] = int(time.time())


def get_deleted_post_uris(state: dict) -> set[str]:
    """Return the set of Bluesky post URIs that have already been deleted."""
    reports = state.setdefault("reports", {})
    uris = reports.setdefault("deleted_post_uris", [])
    return set(uris)


def record_deleted_post_uri(state: dict, post_uri: str) -> None:
    """Record that a Bluesky post has been deleted so it is not retried."""
    reports = state.setdefault("reports", {})
    uris = reports.setdefault("deleted_post_uris", [])
    if post_uri and post_uri not in uris:
        uris.append(post_uri)


def get_acknowledged_report_uris(state: dict) -> set[str]:
    """Return the set of #report reply URIs the bot has already acknowledged."""
    reports = state.setdefault("reports", {})
    uris = reports.setdefault("acknowledged_report_uris", [])
    return set(uris)


def record_acknowledged_report_uri(state: dict, reply_uri: str) -> None:
    """Record a #report reply URI as acknowledged so it is not re-acknowledged."""
    reports = state.setdefault("reports", {})
    uris = reports.setdefault("acknowledged_report_uris", [])
    if reply_uri and reply_uri not in uris:
        uris.append(reply_uri)


def get_liked_reply_uris(state: dict) -> set[str]:
    """Return the set of reply post URIs the bot has already liked."""
    liked_replies = state.setdefault("liked_replies", {})
    uris = liked_replies.setdefault("liked_uris", [])
    return set(uris)


def record_liked_reply_uri(state: dict, uri: str) -> None:
    """Record a reply URI as liked so it is not liked again."""
    liked_replies = state.setdefault("liked_replies", {})
    uris = liked_replies.setdefault("liked_uris", [])
    if uri and uri not in uris:
        uris.append(uri)


def prune_liked_reply_uris(state: dict, max_entries: int = 5000) -> None:
    """Keep only the most recent liked reply URIs."""
    liked_replies = state.setdefault("liked_replies", {})
    uris = liked_replies.setdefault("liked_uris", [])
    if len(uris) > max_entries:
        liked_replies["liked_uris"] = uris[-max_entries:]


def get_likes_last_checked_at(state: dict) -> Optional[int]:
    """Return the epoch timestamp of the last reply-like run, or None."""
    liked_replies = state.setdefault("liked_replies", {})
    return liked_replies.get("last_checked_at")


def set_likes_checked_now(state: dict) -> None:
    """Set the reply-like polling timestamp to current epoch."""
    liked_replies = state.setdefault("liked_replies", {})
    liked_replies["last_checked_at"] = int(time.time())


# ---------------------------------------------------------------------------
# Unfollow history
# ---------------------------------------------------------------------------


def get_unfollowed_dids(state: dict) -> set[str]:
    """Return the set of DIDs the bot has previously unfollowed."""
    history = state.setdefault("unfollow_history", {"entries": []})
    return {e["did"] for e in history.get("entries", [])}


def record_unfollow(state: dict, did: str, reason: str = "not_following_back") -> None:
    """Record that the bot unfollowed a DID, updating the entry if it already exists."""
    history = state.setdefault("unfollow_history", {})
    entries = history.setdefault("entries", [])
    follow_grace = state.setdefault("follow_grace", {})
    grace_entries = follow_grace.setdefault("entries", [])
    follow_grace["entries"] = [e for e in grace_entries if e.get("did") != did]
    for entry in entries:
        if entry["did"] == did:
            entry["unfollowed_at"] = int(time.time())
            entry["reason"] = reason
            return
    entries.append({"did": did, "unfollowed_at": int(time.time()), "reason": reason})


def prune_unfollow_history(state: dict, max_entries: int = 10000) -> None:
    """Keep only the most recent unfollow history entries to bound state file growth."""
    history = state.setdefault("unfollow_history", {})
    entries = history.setdefault("entries", [])
    if len(entries) > max_entries:
        entries.sort(key=lambda e: e.get("unfollowed_at", 0))
        history["entries"] = entries[-max_entries:]


def get_follow_grace_dids(
    state: dict,
    cutoff_ts: float | None = None,
) -> set[str]:
    """Return the set of DIDs still within the follow-response grace window."""
    if cutoff_ts is None:
        cutoff_ts = time.time() - FOLLOW_RESPONSE_GRACE_PERIOD_SECONDS

    follow_grace = state.setdefault("follow_grace", {"entries": []})
    return {
        entry["did"]
        for entry in follow_grace.get("entries", [])
        if entry.get("followed_at", 0) > cutoff_ts
    }


def record_follow_grace(
    state: dict,
    did: str,
    source: str = "follow_fellows",
) -> None:
    """Record a followed DID so unfollow honours the response grace window."""
    follow_grace = state.setdefault("follow_grace", {})
    entries = follow_grace.setdefault("entries", [])
    for entry in entries:
        if entry["did"] == did:
            entry["followed_at"] = int(time.time())
            entry["source"] = source
            return
    entries.append({"did": did, "followed_at": int(time.time()), "source": source})


def prune_follow_grace(
    state: dict,
    cutoff_ts: float | None = None,
    max_entries: int = 10000,
) -> None:
    """Drop expired follow-grace entries and bound state-file growth."""
    if cutoff_ts is None:
        cutoff_ts = time.time() - FOLLOW_RESPONSE_GRACE_PERIOD_SECONDS

    follow_grace = state.setdefault("follow_grace", {})
    entries = follow_grace.setdefault("entries", [])
    entries = [entry for entry in entries if entry.get("followed_at", 0) > cutoff_ts]
    if len(entries) > max_entries:
        entries.sort(key=lambda entry: entry.get("followed_at", 0))
        entries = entries[-max_entries:]
    follow_grace["entries"] = entries


# ---------------------------------------------------------------------------
# Follow-fellows tag rotation
# ---------------------------------------------------------------------------


def get_follow_fellows_tag_offset(state: dict) -> int:
    """Return the current tag-rotation offset for the follow-fellows run."""
    ff = state.setdefault("follow_fellows", {"tag_offset": 0})
    return int(ff.get("tag_offset", 0))


def advance_follow_fellows_tag_offset(state: dict, step: int, total_tags: int) -> None:
    """Advance the tag-rotation offset by step, wrapping around total_tags."""
    ff = state.setdefault("follow_fellows", {"tag_offset": 0})
    current = int(ff.get("tag_offset", 0))
    ff["tag_offset"] = (current + step) % total_tags
