"""Social engagement state helpers."""

from __future__ import annotations

import time

MAX_DEDUPE_ENTRIES = 5000


def _append_bounded_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)
        if len(values) > MAX_DEDUPE_ENTRIES:
            del values[:-MAX_DEDUPE_ENTRIES]


def get_liked_reply_uris(state: dict) -> set[str]:
    """Return the set of reply post URIs the bot has already liked."""
    liked_replies = state.setdefault("liked_replies", {})
    uris = liked_replies.setdefault("liked_uris", [])
    return set(uris)


def record_liked_reply_uri(state: dict, uri: str) -> None:
    """Record a reply URI as liked so it is not liked again."""
    liked_replies = state.setdefault("liked_replies", {})
    uris = liked_replies.setdefault("liked_uris", [])
    _append_bounded_unique(uris, uri)


def prune_liked_reply_uris(state: dict, max_entries: int = 5000) -> None:
    """Keep only the most recent liked reply URIs."""
    liked_replies = state.setdefault("liked_replies", {})
    uris = liked_replies.setdefault("liked_uris", [])
    if len(uris) > max_entries:
        liked_replies["liked_uris"] = uris[-max_entries:]


def get_likes_last_checked_at(state: dict) -> int | None:
    """Return the epoch timestamp of the last reply-like run, or None."""
    liked_replies = state.setdefault("liked_replies", {})
    return liked_replies.get("last_checked_at")


def set_likes_checked_now(state: dict) -> None:
    """Set the reply-like polling timestamp to current epoch."""
    liked_replies = state.setdefault("liked_replies", {})
    liked_replies["last_checked_at"] = int(time.time())


def get_replied_joke_request_uris(state: dict) -> set[str]:
    joke_requests = state.setdefault("joke_requests", {})
    return set(joke_requests.setdefault("replied_uris", []))


def record_replied_joke_request_uri(state: dict, uri: str) -> None:
    joke_requests = state.setdefault("joke_requests", {})
    uris = joke_requests.setdefault("replied_uris", [])
    _append_bounded_unique(uris, uri)


def prune_replied_joke_request_uris(state: dict, max_entries: int = 5000) -> None:
    joke_requests = state.setdefault("joke_requests", {})
    uris = joke_requests.setdefault("replied_uris", [])
    if len(uris) > max_entries:
        joke_requests["replied_uris"] = uris[-max_entries:]


def get_joke_request_checkpoint(state: dict) -> tuple[float | None, set[str]]:
    joke_requests = state.setdefault("joke_requests", {})
    checked_at = joke_requests.setdefault("last_checked_at", None)
    boundary_uris = joke_requests.setdefault("boundary_notification_uris", [])
    return checked_at, set(boundary_uris)


def set_joke_request_checkpoint(
    state: dict, checked_at: float, boundary_notification_uris: set[str]
) -> None:
    joke_requests = state.setdefault("joke_requests", {})
    joke_requests["last_checked_at"] = checked_at
    joke_requests["boundary_notification_uris"] = sorted(
        uri for uri in boundary_notification_uris if uri
    )
