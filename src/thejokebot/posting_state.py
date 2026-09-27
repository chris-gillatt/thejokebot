"""Provider rotation and posted-joke state helpers."""

from __future__ import annotations

import time

PROVIDER_ROTATION_ORDER = ["icanhazdadjoke", "jokeapi", "groandeck", "syrsly"]
PROVIDER_FAILURE_REASONS = (
    "duplicate",
    "too_long",
    "network_error",
    "provider_error",
)


def default_provider_failure() -> dict:
    return {
        "count": 0,
        "last_failure_at": None,
        "last_error": None,
        "reason_counts": dict.fromkeys(PROVIDER_FAILURE_REASONS, 0),
    }


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

    last = state["provider"].get("last_started_primary")
    if last is None:
        last = state["provider"].get("last_used")
    if last is None or last not in rotation:
        return rotation[0]

    index = rotation.index(last)
    return rotation[(index + 1) % len(rotation)]


def record_provider_started(state: dict, provider: str) -> None:
    """Advance rotation by recording the primary selected to start this run."""
    state["provider"]["last_started_primary"] = provider
    state["provider"]["last_started_primary_at"] = int(time.time())


def record_provider_used(state: dict, provider: str) -> None:
    """Record which provider supplied the selected joke this run."""
    state["provider"]["last_used"] = provider
    state["provider"]["last_used_at"] = int(time.time())


def record_failure(
    state: dict,
    provider: str,
    error: str,
    reason_counts: dict[str, int] | None = None,
) -> None:
    """Increment the failure counter for a provider."""
    failures = state["provider"].setdefault("failures", {})
    entry = failures.setdefault(provider, default_provider_failure())
    entry["count"] += 1
    entry["last_failure_at"] = int(time.time())
    entry["last_error"] = str(error)
    saved_counts = entry.setdefault("reason_counts", {})
    for reason in PROVIDER_FAILURE_REASONS:
        saved_counts.setdefault(reason, 0)
    for reason, count in (reason_counts or {}).items():
        if reason in PROVIDER_FAILURE_REASONS:
            saved_counts[reason] += max(0, int(count))


def add_posted_joke(
    state: dict,
    b64: str,
    provider: str,
    post_uri: str | None = None,
    post_cid: str | None = None,
    hashtags: list[str] | None = None,
) -> None:
    """Record a successfully posted joke in state."""
    entry = {"ts": int(time.time()), "b64": b64, "provider": provider}
    if post_uri:
        entry["post_uri"] = post_uri
    if post_cid:
        entry["post_cid"] = post_cid
    if hashtags:
        entry["hashtags"] = list(
            dict.fromkeys(
                tag.strip().removeprefix("#").lower()
                for tag in hashtags
                if tag.strip().removeprefix("#")
            )
        )
    state["posted_jokes"].append(entry)


def get_recent_b64s(state: dict, cutoff_ts: float) -> set:
    """Return the set of base64-encoded jokes posted after cutoff_ts."""
    return {entry["b64"] for entry in state["posted_jokes"] if entry["ts"] > cutoff_ts}


def prune_old_jokes(state: dict, cutoff_ts: float) -> None:
    """Remove joke history entries older than cutoff_ts."""
    state["posted_jokes"] = [
        entry for entry in state["posted_jokes"] if entry["ts"] > cutoff_ts
    ]


def get_post_uri_index(state: dict) -> dict:
    """Map post URI to posted-jokes entries for report lookup."""
    index = {}
    for entry in state.get("posted_jokes", []):
        post_uri = entry.get("post_uri")
        if post_uri:
            index[post_uri] = entry
    return index


def get_posting_tag_offset(state: dict) -> int:
    """Return the current tag-rotation offset for post hashtags."""
    posting = state.setdefault("posting", {"tag_offset": 0})
    return int(posting.get("tag_offset", 0))


def advance_posting_tag_offset(state: dict, step: int, total_tags: int) -> None:
    """Advance post tag-rotation offset by step, wrapping around total_tags."""
    posting = state.setdefault("posting", {"tag_offset": 0})
    current = int(posting.get("tag_offset", 0))
    posting["tag_offset"] = (current + step) % total_tags
