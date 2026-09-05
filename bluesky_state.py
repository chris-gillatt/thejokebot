"""Domain-based runtime state for the joke bot."""

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Callable, Iterator, Optional, TypeVar

# File locking support (Unix-like systems)
if sys.platform != "win32":
    import fcntl
else:
    fcntl = None  # type: ignore

STATE_FILE = str(Path(__file__).resolve().parent / "bot_state.json")
STATE_FILENAMES = {
    "posting": "posting_state.json",
    "social": "social_state.json",
    "moderation": "moderation_state.json",
    "provider_health": "provider_health_state.json",
}
FOLLOW_RESPONSE_GRACE_PERIOD_DAYS = 90
FOLLOW_RESPONSE_GRACE_PERIOD_SECONDS = FOLLOW_RESPONSE_GRACE_PERIOD_DAYS * 24 * 60 * 60
STARTER_PACK_ATTRIBUTION_RETENTION_DAYS = 37

# Canonical provider order — the rotation wraps around this list.
# Add new providers here and they will be included in rotation automatically.
PROVIDER_ROTATION_ORDER = ["icanhazdadjoke", "jokeapi", "groandeck", "syrsly"]
PROVIDER_FAILURE_REASONS = (
    "duplicate",
    "too_long",
    "network_error",
    "provider_error",
)
T = TypeVar("T")
StateReadFailures = dict[str, tuple[str, Exception]]


class StateReadError(RuntimeError):
    """Raised when an update cannot safely read a selected state domain."""

    def __init__(self, failures: StateReadFailures) -> None:
        self.domains = tuple(sorted(failures))
        details = "; ".join(
            f"{domain} ({path}): {error}"
            for domain, (path, error) in sorted(failures.items())
        )
        super().__init__(f"Could not read selected state domain(s): {details}")


def _state_files() -> dict[str, str]:
    state_directory = Path(STATE_FILE).resolve().parent / "state"
    return {
        domain: str(state_directory / filename)
        for domain, filename in STATE_FILENAMES.items()
    }


def _default_provider_failure() -> dict:
    return {
        "count": 0,
        "last_failure_at": None,
        "last_error": None,
        "reason_counts": {reason: 0 for reason in PROVIDER_FAILURE_REASONS},
    }


def _default_state() -> dict:
    return {
        "provider": {
            "last_used": None,
            "last_used_at": None,
            "last_started_primary": None,
            "last_started_primary_at": None,
            "rotation_order": list(PROVIDER_ROTATION_ORDER),
            "failures": {
                p: _default_provider_failure() for p in PROVIDER_ROTATION_ORDER
            },
            "health_checks": {
                p: {
                    "last_check_at": None,
                    "last_check_success": None,
                    "consecutive_failures": 0,
                    "configured": None,
                }
                for p in PROVIDER_ROTATION_ORDER + ["api_ninjas"]
            },
        },
        "reports": {
            "processed_notification_uris": [],
            "unresolved_notification_attempts": {},
            "last_checked_at": None,
            "deleted_post_uris": [],
            "acknowledged_report_uris": [],
            "activity_events": [],
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
        "follow_tracking": {
            "following_snapshot_dids": [],
            "starter_pack_attribution": {
                "coverage_started_at": None,
                "last_checked_at": None,
                "high_water_indexed_at": None,
                "boundary_notification_hashes": [],
                "packs": {},
            },
        },
        "follow_fellows": {
            "tag_offset": 0,
        },
        "posting": {
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
        failure = failures.setdefault(provider_name, _default_provider_failure())
        reason_counts = failure.setdefault("reason_counts", {})
        for reason in PROVIDER_FAILURE_REASONS:
            reason_counts.setdefault(reason, 0)

    health_checks = provider.setdefault("health_checks", {})
    all_providers = list(
        (provider.get("rotation_order") or PROVIDER_ROTATION_ORDER)
    ) + ["api_ninjas"]
    for provider_name in all_providers:
        health_checks.setdefault(
            provider_name,
            {
                "last_check_at": None,
                "last_check_success": None,
                "consecutive_failures": 0,
                "configured": None,
            },
        )
        health_checks[provider_name].setdefault("configured", None)

    reports = state.setdefault("reports", {})
    reports.setdefault("processed_notification_uris", [])
    reports.setdefault("unresolved_notification_attempts", {})
    reports.setdefault("last_checked_at", None)
    reports.setdefault("deleted_post_uris", [])
    reports.setdefault("acknowledged_report_uris", [])
    reports.setdefault("activity_events", [])

    liked_replies = state.setdefault("liked_replies", {})
    liked_replies.setdefault("liked_uris", [])
    liked_replies.setdefault("last_checked_at", None)

    unfollow_history = state.setdefault("unfollow_history", {})
    unfollow_history.setdefault("entries", [])

    follow_grace = state.setdefault("follow_grace", {})
    follow_grace.setdefault("entries", [])

    follow_tracking = state.setdefault("follow_tracking", {})
    follow_tracking.setdefault("following_snapshot_dids", [])
    attribution = follow_tracking.setdefault("starter_pack_attribution", {})
    attribution.setdefault("coverage_started_at", None)
    attribution.setdefault("last_checked_at", None)
    attribution.setdefault("high_water_indexed_at", None)
    attribution.setdefault("boundary_notification_hashes", [])
    attribution.setdefault("packs", {})

    follow_fellows_state = state.setdefault("follow_fellows", {})
    follow_fellows_state.setdefault("tag_offset", 0)

    posting_state = state.setdefault("posting", {})
    posting_state.setdefault("tag_offset", 0)

    state.setdefault("posted_jokes", [])
    return state


def _normalise_domains(domains: str | tuple[str, ...]) -> tuple[str, ...]:
    selected = domains if isinstance(domains, tuple) else (domains,)
    unknown = set(selected) - set(STATE_FILENAMES)
    if unknown:
        raise ValueError(f"Unknown state domain(s): {', '.join(sorted(unknown))}")
    return selected


@contextmanager
def _state_locks(domains: tuple[str, ...], exclusive: bool) -> Iterator[None]:
    if fcntl is None:
        yield
        return

    lock_mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    with ExitStack() as stack:
        for domain in sorted(domains):
            state_file = _state_files()[domain]
            Path(state_file).parent.mkdir(parents=True, exist_ok=True)
            lock_file = stack.enter_context(
                open(state_file + ".lock", "w", encoding="utf-8")
            )
            fcntl.flock(lock_file.fileno(), lock_mode)
            stack.callback(fcntl.flock, lock_file.fileno(), fcntl.LOCK_UN)
        yield


def load_state() -> dict:
    """Load and assemble all state domains, with legacy-file fallback."""
    domains = tuple(STATE_FILENAMES)
    try:
        with _state_locks(domains, exclusive=False):
            state, failures = _load_state_unlocked()
    except OSError as exc:
        print(f"Warning: could not read bot state; starting with empty state: {exc}")
        return _default_state()
    _warn_state_read_failures(failures)
    return state


def save_state(state: dict, *, domains: str | tuple[str, ...]) -> None:
    """Atomically persist only the selected state domains."""
    selected = _normalise_domains(domains)
    with _state_locks(selected, exclusive=True):
        for domain in selected:
            _save_domain_unlocked(state, domain)


def update_state(
    mutator: Callable[[dict], T],
    *,
    domains: str | tuple[str, ...],
) -> T:
    """
    Mutate state while holding the write lock for the full read-modify-write cycle.

    Prefer this for new state writers. It prevents a stale in-memory snapshot from
    overwriting changes written by another run between load_state() and save_state().
    """
    selected = _normalise_domains(domains)
    with _state_locks(selected, exclusive=True):
        state, failures = _load_state_unlocked()
        selected_failures = {
            domain: failures[domain] for domain in selected if domain in failures
        }
        if selected_failures:
            raise StateReadError(selected_failures)
        _warn_state_read_failures(failures)
        result = mutator(state)
        for domain in selected:
            _save_domain_unlocked(state, domain)
        return result


def _load_state_unlocked() -> tuple[dict, StateReadFailures]:
    legacy_state = {}
    legacy_failure = None
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as state_file:
                legacy_state = json.load(state_file)
        except (json.JSONDecodeError, OSError) as exc:
            legacy_failure = (STATE_FILE, exc)
    state = _normalise_state(legacy_state)
    failures: StateReadFailures = {}

    for domain, state_file_path in _state_files().items():
        if not os.path.exists(state_file_path):
            if legacy_failure is not None:
                failures[domain] = legacy_failure
            continue
        try:
            with open(state_file_path, encoding="utf-8") as state_file:
                payload = json.load(state_file)
        except (json.JSONDecodeError, OSError) as exc:
            failures[domain] = (state_file_path, exc)
            continue
        if domain == "provider_health":
            state["provider"]["health_checks"] = payload.get("health_checks", {})
        else:
            state.update(payload)
    return _normalise_state(state), failures


def _warn_state_read_failures(failures: StateReadFailures) -> None:
    for domain, (path, error) in sorted(failures.items()):
        print(f"Warning: could not read {domain} state from {path}: {error}")


def _domain_payload(state: dict, domain: str) -> dict:
    if domain == "posting":
        provider = dict(state["provider"])
        provider.pop("health_checks", None)
        return {
            "provider": provider,
            "posting": state["posting"],
            "posted_jokes": state["posted_jokes"],
        }
    if domain == "social":
        return {
            key: state[key]
            for key in (
                "liked_replies",
                "unfollow_history",
                "follow_grace",
                "follow_tracking",
                "follow_fellows",
            )
        }
    if domain == "moderation":
        return {"reports": state["reports"]}
    return {"health_checks": state["provider"]["health_checks"]}


def _save_domain_unlocked(state: dict, domain: str) -> None:
    state_file_path = _state_files()[domain]
    Path(state_file_path).parent.mkdir(parents=True, exist_ok=True)
    temporary_path = state_file_path + ".tmp"
    with open(temporary_path, "w", encoding="utf-8") as state_file:
        json.dump(
            _domain_payload(_normalise_state(state), domain), state_file, indent=2
        )
        state_file.write("\n")
    os.replace(temporary_path, state_file_path)


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
        # Preserve the existing cursor when migrating older state files.
        last = state["provider"].get("last_used")
    if last is None or last not in rotation:
        return rotation[0]

    idx = rotation.index(last)
    return rotation[(idx + 1) % len(rotation)]


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
    entry = failures.setdefault(provider, _default_provider_failure())
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
# Follow tracking snapshots
# ---------------------------------------------------------------------------


def get_following_snapshot_dids(state: dict) -> set[str]:
    """Return the previous unfollow-run snapshot of currently followed DIDs."""
    follow_tracking = state.setdefault("follow_tracking", {})
    dids = follow_tracking.setdefault("following_snapshot_dids", [])
    return {str(did).strip() for did in dids if str(did).strip()}


def set_following_snapshot_dids(state: dict, dids: set[str]) -> None:
    """Persist a deterministic snapshot of currently followed DIDs."""
    follow_tracking = state.setdefault("follow_tracking", {})
    follow_tracking["following_snapshot_dids"] = sorted(
        {str(did).strip() for did in dids if str(did).strip()}
    )


def get_starter_pack_attribution(state: dict) -> dict:
    """Return the normalised starter-pack attribution state."""
    _normalise_state(state)
    return state["follow_tracking"]["starter_pack_attribution"]


def record_starter_pack_attribution_scan(
    state: dict,
    *,
    coverage_started_at: str,
    checked_at: str,
    high_water_indexed_at: str | None,
    boundary_notification_hashes: set[str],
    observations: list[dict],
    cutoff_date: str,
) -> None:
    """Merge a completed starter-pack notification scan into social state."""
    attribution = get_starter_pack_attribution(state)
    if attribution["coverage_started_at"] is None:
        attribution["coverage_started_at"] = coverage_started_at
    attribution["last_checked_at"] = checked_at
    attribution["high_water_indexed_at"] = high_water_indexed_at
    attribution["boundary_notification_hashes"] = sorted(
        {value for value in boundary_notification_hashes if value}
    )

    packs = attribution["packs"]
    for observation in observations:
        pack_uri = str(observation.get("pack_uri") or "").strip()
        observed_date = str(observation.get("date") or "").strip()
        if not pack_uri or not observed_date:
            continue
        pack = packs.setdefault(pack_uri, {"daily_counts": {}})
        pack["name"] = str(observation.get("name") or "Starter pack").strip()
        pack["creator_handle"] = str(observation.get("creator_handle") or "").strip()
        pack["last_observed_at"] = str(observation.get("observed_at") or checked_at)
        daily_counts = pack.setdefault("daily_counts", {})
        daily_counts[observed_date] = int(daily_counts.get(observed_date) or 0) + 1

    for pack_uri, pack in list(packs.items()):
        daily_counts = pack.setdefault("daily_counts", {})
        pack["daily_counts"] = {
            date: int(count)
            for date, count in sorted(daily_counts.items())
            if date >= cutoff_date and int(count) > 0
        }
        if not pack["daily_counts"]:
            del packs[pack_uri]


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


# ---------------------------------------------------------------------------
# Posting tag rotation
# ---------------------------------------------------------------------------


def get_posting_tag_offset(state: dict) -> int:
    """Return the current tag-rotation offset for post hashtags."""
    posting = state.setdefault("posting", {"tag_offset": 0})
    return int(posting.get("tag_offset", 0))


def advance_posting_tag_offset(state: dict, step: int, total_tags: int) -> None:
    """Advance post tag-rotation offset by step, wrapping around total_tags."""
    posting = state.setdefault("posting", {"tag_offset": 0})
    current = int(posting.get("tag_offset", 0))
    posting["tag_offset"] = (current + step) % total_tags
