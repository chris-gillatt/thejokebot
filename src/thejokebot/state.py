"""Domain-based runtime state for the joke bot."""

from __future__ import annotations

import hashlib
import sys
import time
from typing import Callable, TypeVar

from thejokebot import moderation_state, posting_state
from thejokebot import social_state
from thejokebot.paths import LEGACY_STATE_FILE, LOCKS_DIR
from thejokebot import state_store

# File locking support (Unix-like systems)
if sys.platform != "win32":
    import fcntl
else:
    fcntl = None  # type: ignore

STATE_FILE = str(LEGACY_STATE_FILE)
STATE_FILENAMES = {
    "posting": "posting_state.json",
    "social": "social_state.json",
    "moderation": "moderation_state.json",
    "provider_health": "provider_health_state.json",
}
FOLLOW_RESPONSE_GRACE_PERIOD_DAYS = 90
FOLLOW_RESPONSE_GRACE_PERIOD_SECONDS = FOLLOW_RESPONSE_GRACE_PERIOD_DAYS * 24 * 60 * 60
STARTER_PACK_ATTRIBUTION_RETENTION_DAYS = 37
ACQUISITION_COHORT_SCHEMA_VERSION = 1
ACQUISITION_COHORT_SOURCES = ("followback", "interaction", "discovery")
ACQUISITION_COHORT_CHECKPOINT_DAYS = (30, 90)

PROVIDER_ROTATION_ORDER = posting_state.PROVIDER_ROTATION_ORDER
PROVIDER_FAILURE_REASONS = posting_state.PROVIDER_FAILURE_REASONS
_default_provider_failure = posting_state.default_provider_failure
get_next_provider = posting_state.get_next_provider
record_provider_started = posting_state.record_provider_started
record_provider_used = posting_state.record_provider_used
record_failure = posting_state.record_failure
add_posted_joke = posting_state.add_posted_joke
get_recent_b64s = posting_state.get_recent_b64s
prune_old_jokes = posting_state.prune_old_jokes
get_post_uri_index = posting_state.get_post_uri_index
get_posting_tag_offset = posting_state.get_posting_tag_offset
advance_posting_tag_offset = posting_state.advance_posting_tag_offset
get_processed_notification_uris = moderation_state.get_processed_notification_uris
record_processed_notification = moderation_state.record_processed_notification
get_unresolved_notification_attempts = (
    moderation_state.get_unresolved_notification_attempts
)
increment_unresolved_notification_attempt = (
    moderation_state.increment_unresolved_notification_attempt
)
clear_unresolved_notification_attempt = (
    moderation_state.clear_unresolved_notification_attempt
)
prune_unresolved_notification_attempts = (
    moderation_state.prune_unresolved_notification_attempts
)
prune_processed_notifications = moderation_state.prune_processed_notifications
set_reports_checked_now = moderation_state.set_reports_checked_now
record_moderation_activity = moderation_state.record_moderation_activity
get_deleted_post_uris = moderation_state.get_deleted_post_uris
record_deleted_post_uri = moderation_state.record_deleted_post_uri
get_acknowledged_report_uris = moderation_state.get_acknowledged_report_uris
record_acknowledged_report_uri = moderation_state.record_acknowledged_report_uri
get_liked_reply_uris = social_state.get_liked_reply_uris
record_liked_reply_uri = social_state.record_liked_reply_uri
prune_liked_reply_uris = social_state.prune_liked_reply_uris
get_likes_last_checked_at = social_state.get_likes_last_checked_at
set_likes_checked_now = social_state.set_likes_checked_now
get_replied_joke_request_uris = social_state.get_replied_joke_request_uris
record_replied_joke_request_uri = social_state.record_replied_joke_request_uri
prune_replied_joke_request_uris = social_state.prune_replied_joke_request_uris
get_joke_request_checkpoint = social_state.get_joke_request_checkpoint
set_joke_request_checkpoint = social_state.set_joke_request_checkpoint
T = TypeVar("T")
StateReadFailures = state_store.StateReadFailures
StateReadError = state_store.StateReadError


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
        "joke_requests": {
            "replied_uris": [],
            "last_checked_at": None,
            "boundary_notification_uris": [],
        },
        "unfollow_history": {
            "entries": [],
        },
        "follow_grace": {
            "entries": [],
        },
        "follow_tracking": {
            "following_snapshot_dids": [],
            "acquisition_cohorts": {
                "schema_version": ACQUISITION_COHORT_SCHEMA_VERSION,
                "coverage_started_at": None,
                "members": {},
                "cohorts": {},
            },
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

    joke_requests = state.setdefault("joke_requests", {})
    joke_requests.setdefault("replied_uris", [])
    joke_requests.setdefault("last_checked_at", None)
    joke_requests.setdefault("boundary_notification_uris", [])

    unfollow_history = state.setdefault("unfollow_history", {})
    unfollow_history.setdefault("entries", [])

    follow_grace = state.setdefault("follow_grace", {})
    follow_grace.setdefault("entries", [])

    follow_tracking = state.setdefault("follow_tracking", {})
    follow_tracking.setdefault("following_snapshot_dids", [])
    acquisition_cohorts = follow_tracking.setdefault("acquisition_cohorts", {})
    acquisition_cohorts.setdefault("schema_version", ACQUISITION_COHORT_SCHEMA_VERSION)
    acquisition_cohorts.setdefault("coverage_started_at", None)
    acquisition_cohorts.setdefault("members", {})
    acquisition_cohorts.setdefault("cohorts", {})
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


def _merge_domain_payload(state: dict, domain: str, payload: dict) -> None:
    if domain == "provider_health":
        state["provider"]["health_checks"] = payload.get("health_checks", {})
    else:
        state.update(payload)


def load_state() -> dict:
    """Load and assemble all state domains, with legacy-file fallback."""
    return state_store.load_state(
        state_file=STATE_FILE,
        state_filenames=STATE_FILENAMES,
        lock_dir_name=LOCKS_DIR.name,
        fcntl_module=fcntl,
        default_state=_default_state,
        normalise_state=_normalise_state,
        merge_domain_payload=_merge_domain_payload,
    )


def save_state(state: dict, *, domains: str | tuple[str, ...]) -> None:
    """Atomically persist only the selected state domains."""
    state_store.save_state(
        state,
        domains=domains,
        state_file=STATE_FILE,
        state_filenames=STATE_FILENAMES,
        lock_dir_name=LOCKS_DIR.name,
        fcntl_module=fcntl,
        normalise_state=_normalise_state,
        domain_payload=_domain_payload,
    )


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
    return state_store.update_state(
        mutator,
        domains=domains,
        state_file=STATE_FILE,
        state_filenames=STATE_FILENAMES,
        lock_dir_name=LOCKS_DIR.name,
        fcntl_module=fcntl,
        normalise_state=_normalise_state,
        merge_domain_payload=_merge_domain_payload,
        domain_payload=_domain_payload,
    )


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
                "joke_requests",
                "unfollow_history",
                "follow_grace",
                "follow_tracking",
                "follow_fellows",
            )
        }
    if domain == "moderation":
        return {"reports": state["reports"]}
    return {"health_checks": state["provider"]["health_checks"]}


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


def _acquisition_member_hash(did: str) -> str:
    return hashlib.sha256(did.strip().encode("utf-8")).hexdigest()


def get_acquisition_cohorts(state: dict) -> dict:
    """Return the normalised private acquisition-cohort state."""
    _normalise_state(state)
    return state["follow_tracking"]["acquisition_cohorts"]


def _acquisition_source_totals(cohorts: dict, month: str, source: str) -> dict:
    month_totals = cohorts["cohorts"].setdefault(month, {})
    return month_totals.setdefault(
        source,
        {
            "acquired": 0,
            "checkpoints": {
                str(days): {"observed": 0, "still_following": 0}
                for days in ACQUISITION_COHORT_CHECKPOINT_DAYS
            },
        },
    )


def record_acquisition(
    state: dict,
    did: str,
    source: str,
    *,
    acquired_at: int | None = None,
) -> bool:
    """Record one acquisition per account during its open 90-day window."""
    normalised_did = did.strip()
    if not normalised_did:
        raise ValueError("Acquisition DID must not be empty")
    if source not in ACQUISITION_COHORT_SOURCES:
        raise ValueError(f"Unknown acquisition source: {source}")

    cohorts = get_acquisition_cohorts(state)
    member_hash = _acquisition_member_hash(normalised_did)
    if member_hash in cohorts["members"]:
        return False

    acquired_timestamp = int(time.time()) if acquired_at is None else int(acquired_at)
    cohort_month = time.strftime("%Y-%m", time.gmtime(acquired_timestamp))
    cohorts["members"][member_hash] = {
        "source": source,
        "acquired_at": acquired_timestamp,
        "cohort_month": cohort_month,
        "checkpoints": {str(days): None for days in ACQUISITION_COHORT_CHECKPOINT_DAYS},
    }
    source_totals = _acquisition_source_totals(cohorts, cohort_month, source)
    source_totals["acquired"] += 1
    if cohorts["coverage_started_at"] is None:
        cohorts["coverage_started_at"] = acquired_timestamp
    else:
        cohorts["coverage_started_at"] = min(
            int(cohorts["coverage_started_at"]), acquired_timestamp
        )
    return True


def reconcile_acquisition_cohorts(
    state: dict,
    follower_dids: set[str],
    *,
    observed_at: int | None = None,
) -> dict[str, dict[str, int]]:
    """Observe due 30/90-day checkpoints against a complete follower set."""
    observed_timestamp = int(time.time()) if observed_at is None else int(observed_at)
    follower_hashes = {
        _acquisition_member_hash(did)
        for did in follower_dids
        if isinstance(did, str) and did.strip()
    }
    cohorts = get_acquisition_cohorts(state)
    result = {
        str(days): {"observed": 0, "still_following": 0}
        for days in ACQUISITION_COHORT_CHECKPOINT_DAYS
    }

    for member_hash, member in list(cohorts["members"].items()):
        acquired_at = int(member.get("acquired_at") or 0)
        source = str(member.get("source") or "")
        cohort_month = str(member.get("cohort_month") or "")
        if source not in ACQUISITION_COHORT_SOURCES or not cohort_month:
            continue
        checkpoints = member.setdefault("checkpoints", {})
        source_totals = _acquisition_source_totals(cohorts, cohort_month, source)
        for days in ACQUISITION_COHORT_CHECKPOINT_DAYS:
            checkpoint = str(days)
            if checkpoints.get(checkpoint) is not None:
                continue
            if observed_timestamp < acquired_at + days * 24 * 60 * 60:
                continue
            still_following = member_hash in follower_hashes
            checkpoints[checkpoint] = {
                "observed_at": observed_timestamp,
                "still_following": still_following,
            }
            checkpoint_totals = source_totals["checkpoints"][checkpoint]
            checkpoint_totals["observed"] += 1
            checkpoint_totals["still_following"] += int(still_following)
            result[checkpoint]["observed"] += 1
            result[checkpoint]["still_following"] += int(still_following)

        if checkpoints.get("90") is not None:
            del cohorts["members"][member_hash]

    return result


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
