"""Moderation and report-processing state helpers."""

from __future__ import annotations

import time


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


def get_unresolved_notification_attempts(state: dict) -> dict[str, int]:
    """Return per-notification unresolved-attempt counters for report ingestion."""
    reports = state.setdefault("reports", {})
    attempts = reports.setdefault("unresolved_notification_attempts", {})
    if not isinstance(attempts, dict):
        reports["unresolved_notification_attempts"] = {}
        attempts = reports["unresolved_notification_attempts"]
    return attempts


def increment_unresolved_notification_attempt(
    state: dict, notification_uri: str
) -> int:
    """Increment unresolved-attempt counter for a notification URI."""
    if not notification_uri:
        return 0
    attempts = get_unresolved_notification_attempts(state)
    previous = attempts.get(notification_uri, 0)
    if not isinstance(previous, int) or previous < 0:
        previous = 0
    current = previous + 1
    attempts[notification_uri] = current
    return current


def clear_unresolved_notification_attempt(state: dict, notification_uri: str) -> None:
    """Clear unresolved-attempt counter for a notification URI."""
    if not notification_uri:
        return
    attempts = get_unresolved_notification_attempts(state)
    attempts.pop(notification_uri, None)


def prune_unresolved_notification_attempts(
    state: dict, max_entries: int = 5000
) -> None:
    """Keep only the most recent unresolved-attempt entries."""
    reports = state.setdefault("reports", {})
    attempts = get_unresolved_notification_attempts(state)
    if len(attempts) > max_entries:
        keys_to_keep = list(attempts.keys())[-max_entries:]
        reports["unresolved_notification_attempts"] = {
            key: attempts[key] for key in keys_to_keep
        }


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


def record_moderation_activity(
    state: dict,
    proposals: int,
    acknowledgements: int,
    approved_removals: int,
    unresolved: int,
    recorded_at: int | None = None,
    max_events: int = 540,
) -> None:
    """Record a bounded aggregate moderation event without report identifiers."""
    reports = state.setdefault("reports", {})
    events = reports.setdefault("activity_events", [])
    events.append(
        {
            "recorded_at": int(recorded_at if recorded_at is not None else time.time()),
            "proposals": max(0, int(proposals)),
            "acknowledgements": max(0, int(acknowledgements)),
            "approved_removals": max(0, int(approved_removals)),
            "unresolved": max(0, int(unresolved)),
        }
    )
    if len(events) > max_events:
        reports["activity_events"] = events[-max_events:]


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
