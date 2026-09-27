"""Follow back new followers and like reply/repost interactions."""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timedelta, timezone

import requests
import atproto_client.exceptions
from colorama import Fore, Style

from thejokebot import blocks as blocks
from thejokebot import config as runtime_config
from thejokebot import state as bot_state
from thejokebot.commands import follow_back as follow_back_processing
from thejokebot.commands import follow_interactors as follow_interactor_processing
from thejokebot.commands import joke_requests
from thejokebot.runtime import (
    get_nested_value,
    get_runtime_controls,
    login_client,
    mask_sensitive,
    retry_network_call,
)

_FOLLOWS_AND_LIKES_CONFIG = runtime_config.get_follows_and_likes_config()

_DEFAULT_LIKE_MAX_PAGES = _FOLLOWS_AND_LIKES_CONFIG["like_max_pages"]
_DEFAULT_LIKE_PAGE_LIMIT = _FOLLOWS_AND_LIKES_CONFIG["like_page_limit"]
_LIKE_WINDOW_SECONDS = 24 * 60 * 60  # only like replies from the last 24 hours
_LIKE_REASONS = ("reply", "repost")
_UTC_OFFSET = "+00:00"

# Transitional aliases keep the existing test seam stable while the social test
# suite is split by domain later in this phase.
_joke_request_candidate = joke_requests.request_candidate
_select_reply_joke = joke_requests.select_reply_joke
_JOKE_REQUEST_MAX_PAGES = joke_requests._MAX_PAGES
joke_denylist = joke_requests.joke_denylist
joke_posting = joke_requests.joke_posting

_FOLLOW_BACK_PAGE_LIMIT = follow_back_processing.PAGE_LIMIT
_FOLLOW_BACK_MAX_PAGES = follow_back_processing.MAX_PAGES
_FOLLOW_BACK_MAX_RUNTIME_SECONDS = follow_back_processing.MAX_RUNTIME_SECONDS
_STARTER_PACK_WINDOW_DAYS = 30
_STARTER_PACK_MAX_PAGES = 20
_STARTER_PACK_PAGE_LIMIT = 100
_STARTER_PACK_URI_PATTERN = re.compile(
    r"^at://(?P<creator>[^/]+)/app\.bsky\.graph\.starterpack/(?P<rkey>[^/]+)$"
)
_SOCIAL_SUMMARY_FIELDS = (
    "follow_back_candidates",
    "follow_back_added",
    "protected",
    "interaction_candidates",
    "interaction_eligible",
    "interaction_added",
    "interactions_liked",
    "joke_replies",
    "starter_pack_follows",
    "starter_pack_scan_complete",
    "failed",
)


def _social_summary_line(summary: dict, dry_run: bool) -> str:
    counts = ", ".join(
        f"{field}={int(summary.get(field) or 0)}" for field in _SOCIAL_SUMMARY_FIELDS
    )
    return f"Social summary: {counts}, dry_run={'true' if dry_run else 'false'}."


def reply_to_joke_requests(client, username, state, dry_run, summary=None):
    """Delegate joke requests to their domain module."""
    joke_requests.retry_network_call = retry_network_call
    joke_requests.select_reply_joke = _select_reply_joke
    joke_requests._MAX_PAGES = _JOKE_REQUEST_MAX_PAGES
    return joke_requests.reply_to_joke_requests(
        client, username, state, dry_run, summary
    )


def follow_back(
    client,
    dry_run: bool,
    action_delay_seconds: float,
    summary: dict | None = None,
    state: dict | None = None,
) -> None:
    """Delegate follower reconciliation to its domain module."""
    return follow_back_processing.follow_back(
        client,
        dry_run,
        action_delay_seconds,
        summary,
        state,
    )


def _parse_notification_epoch(notification):
    """Parse a notification timestamp into a Unix timestamp, when valid."""
    indexed_at = get_nested_value(notification, "indexed_at") or get_nested_value(
        notification, "indexedAt"
    )
    if not indexed_at:
        return None
    try:
        return datetime.fromisoformat(indexed_at.replace("Z", _UTC_OFFSET)).timestamp()
    except (ValueError, AttributeError):
        return None


def follow_interactors(
    client,
    state: dict,
    dry_run: bool,
    action_delay_seconds: float,
    summary: dict | None = None,
) -> int:
    """Delegate interaction-follow processing to its domain module."""
    return follow_interactor_processing.follow_interactors(
        client, state, dry_run, action_delay_seconds, summary
    )


# ---------------------------------------------------------------------------
# Reply likes
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Starter-pack attribution
# ---------------------------------------------------------------------------


def _starter_pack_observation(notification) -> dict | None:
    """Return public pack metadata for an attributed follow notification."""
    if get_nested_value(notification, "reason") != "follow":
        return None
    starter_pack = get_nested_value(notification, "starter_pack") or get_nested_value(
        notification, "starterPack"
    )
    pack_uri = str(get_nested_value(starter_pack, "uri") or "").strip()
    if not _STARTER_PACK_URI_PATTERN.fullmatch(pack_uri):
        return None
    indexed_at = get_nested_value(notification, "indexed_at") or get_nested_value(
        notification, "indexedAt"
    )
    try:
        observed_at = datetime.fromisoformat(
            str(indexed_at).replace("Z", _UTC_OFFSET)
        ).astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None
    return {
        "pack_uri": pack_uri,
        "name": str(get_nested_value(starter_pack, "record", "name") or "Starter pack"),
        "creator_handle": str(
            get_nested_value(starter_pack, "creator", "handle") or ""
        ),
        "observed_at": observed_at.isoformat().replace(_UTC_OFFSET, "Z"),
        "date": observed_at.date().isoformat(),
    }


def _notification_hash(notification) -> str:
    uri = str(get_nested_value(notification, "uri") or "")
    return hashlib.sha256(uri.encode("utf-8")).hexdigest() if uri else ""


def _update_starter_pack_page_boundary(
    notification, notification_epoch, notification_hash, page_state
):
    indexed_at = get_nested_value(notification, "indexed_at") or get_nested_value(
        notification, "indexedAt"
    )
    if (
        page_state["newest_epoch"] is None
        or notification_epoch > page_state["newest_epoch"]
    ):
        page_state["newest_epoch"] = notification_epoch
        page_state["newest_indexed_at"] = str(indexed_at)
        page_state["boundary_hashes"] = set()
    if notification_epoch == page_state["newest_epoch"] and notification_hash:
        page_state["boundary_hashes"].add(notification_hash)


def _record_starter_pack_observation(
    notification,
    notification_epoch,
    notification_hash,
    stop_epoch,
    previous_boundary_hashes,
    page_state,
):
    observation = _starter_pack_observation(notification)
    if observation is None or not notification_hash:
        return
    if notification_hash in page_state["seen_hashes"]:
        return
    page_state["seen_hashes"].add(notification_hash)
    if (
        notification_epoch == stop_epoch
        and notification_hash in previous_boundary_hashes
    ):
        return
    page_state["observations"].append(observation)


def _process_starter_pack_page(
    notifications,
    stop_epoch: float,
    previous_boundary_hashes: set[str],
    page_state: dict,
) -> bool:
    """Add unseen observations from one page and report whether to stop paging."""
    for notification in notifications:
        notification_epoch = _parse_notification_epoch(notification)
        if notification_epoch is None:
            continue
        notification_hash = _notification_hash(notification)
        _update_starter_pack_page_boundary(
            notification, notification_epoch, notification_hash, page_state
        )
        if notification_epoch < stop_epoch:
            return True
        _record_starter_pack_observation(
            notification,
            notification_epoch,
            notification_hash,
            stop_epoch,
            previous_boundary_hashes,
            page_state,
        )
    return False


def _collect_starter_pack_attribution(
    client, state: dict, now: datetime
) -> dict | None:
    """Collect a complete incremental scan of starter-pack follow attribution."""
    attribution = bot_state.get_starter_pack_attribution(state)
    high_water = attribution.get("high_water_indexed_at")
    previous_boundary_hashes = set(attribution.get("boundary_notification_hashes", []))
    bootstrap_cutoff = now - timedelta(days=_STARTER_PACK_WINDOW_DAYS)
    stop_epoch = (
        datetime.fromisoformat(high_water.replace("Z", _UTC_OFFSET)).timestamp()
        if high_water
        else bootstrap_cutoff.timestamp()
    )
    cursor = None
    seen_cursors: set[str] = set()
    page_state = {
        "seen_hashes": set(),
        "observations": [],
        "newest_indexed_at": None,
        "newest_epoch": None,
        "boundary_hashes": set(),
    }
    complete = False

    for _ in range(_STARTER_PACK_MAX_PAGES):
        try:
            response = retry_network_call(
                lambda current_cursor=cursor: (
                    client.app.bsky.notification.list_notifications(
                        params={
                            "cursor": current_cursor,
                            "limit": _STARTER_PACK_PAGE_LIMIT,
                            "reasons": ["follow"],
                        }
                    )
                ),
                description="listing starter-pack follow notifications",
            )
        except (
            requests.RequestException,
            TimeoutError,
            atproto_client.exceptions.NetworkError,
            atproto_client.exceptions.RequestException,
        ) as exc:
            print(
                f"{Fore.RED}Failed to fetch starter-pack follows: {exc}{Style.RESET_ALL}"
            )
            return None

        complete = _process_starter_pack_page(
            get_nested_value(response, "notifications") or [],
            stop_epoch,
            previous_boundary_hashes,
            page_state,
        )

        if complete:
            break
        next_cursor = get_nested_value(response, "cursor")
        if not next_cursor:
            complete = True
            break
        if next_cursor in seen_cursors:
            return None
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    if not complete:
        return None
    return {
        "coverage_started_at": (
            attribution.get("coverage_started_at")
            or bootstrap_cutoff.isoformat().replace(_UTC_OFFSET, "Z")
        ),
        "checked_at": now.isoformat().replace(_UTC_OFFSET, "Z"),
        "high_water_indexed_at": page_state["newest_indexed_at"] or high_water,
        "boundary_notification_hashes": page_state["boundary_hashes"],
        "observations": page_state["observations"],
        "cutoff_date": (
            now - timedelta(days=bot_state.STARTER_PACK_ATTRIBUTION_RETENTION_DAYS)
        )
        .date()
        .isoformat(),
    }


def track_starter_pack_follows(
    client, state: dict, dry_run: bool, summary: dict | None = None
) -> int:
    """Track aggregate follows attributed to starter packs."""
    if summary is None:
        summary = {}
    scan = _collect_starter_pack_attribution(client, state, datetime.now(timezone.utc))
    summary["starter_pack_scan_complete"] = int(scan is not None)
    if scan is None:
        summary["starter_pack_follows"] = 0
        return 0
    count = len(scan["observations"])
    summary["starter_pack_follows"] = count
    if not dry_run:
        bot_state.record_starter_pack_attribution_scan(state, **scan)
    return count


def _like_candidate(notification, cutoff_epoch, already_liked):
    reason = get_nested_value(notification, "reason")
    if reason not in _LIKE_REASONS:
        return None, False
    notification_epoch = _parse_notification_epoch(notification)
    if notification_epoch is not None and notification_epoch < cutoff_epoch:
        return None, True
    uri = get_nested_value(notification, "uri")
    cid = get_nested_value(notification, "cid")
    if not uri or not cid:
        return None, False
    reply_text = get_nested_value(notification, "record", "text") or ""
    if re.search(r"(?:^|\s)#report\b", reply_text, re.IGNORECASE):
        return None, False
    if uri in already_liked:
        return None, False
    return (reason, uri, cid), False


def _like_notification(client, reason, uri, cid, dry_run, summary):
    masked_uri = mask_sensitive(uri)
    if dry_run:
        print(
            f"{Fore.YELLOW}[DRY-RUN] Would like {reason}: {masked_uri}{Style.RESET_ALL}"
        )
        return True
    try:
        retry_network_call(
            lambda: client.like(uri=uri, cid=cid),
            description=f"liking {reason} {masked_uri}",
        )
        print(f"{Fore.GREEN}Liked {reason}: {masked_uri}{Style.RESET_ALL}")
        return True
    except (
        requests.RequestException,
        TimeoutError,
        atproto_client.exceptions.NetworkError,
    ) as exc:
        print(f"{Fore.RED}Failed to like {masked_uri}: {exc}{Style.RESET_ALL}")
        summary["failed"] = summary.get("failed", 0) + 1
        return False


def _process_like_page(
    client,
    state,
    notifications,
    cutoff_epoch,
    already_liked,
    dry_run,
    action_delay_seconds,
    summary,
):
    """Process one page of notifications, liking applicable items.

    Mutates ``already_liked`` to track URIs liked during this call.
    Returns ``(new_likes_count, stop_paging)``.
    """
    new_likes = 0
    stop_paging = False
    for notification in notifications:
        candidate, stop_paging = _like_candidate(
            notification, cutoff_epoch, already_liked
        )
        if stop_paging:
            break
        if candidate is None:
            continue
        reason, uri, cid = candidate
        if not _like_notification(client, reason, uri, cid, dry_run, summary):
            continue

        bot_state.record_liked_reply_uri(state, uri)
        already_liked.add(uri)
        new_likes += 1

        if action_delay_seconds > 0:
            time.sleep(action_delay_seconds)

    return new_likes, stop_paging


def like_replies(
    client,
    state: dict,
    dry_run: bool,
    action_delay_seconds: float,
    summary: dict | None = None,
) -> int:
    """Like replies/reposts of the bot's posts from the last 24 hours.

    Notifications older than _LIKE_WINDOW_SECONDS are skipped. Already-liked
    URIs (tracked in state) are also skipped. State is saved after each page
    so progress survives an interruption.

    Returns the number of new likes performed.
    """
    already_liked = bot_state.get_liked_reply_uris(state)
    if summary is None:
        summary = {}
    liked_count = 0
    cutoff_epoch = time.time() - _LIKE_WINDOW_SECONDS
    cursor = None

    for _ in range(_DEFAULT_LIKE_MAX_PAGES):
        try:
            response = retry_network_call(
                lambda: client.app.bsky.notification.list_notifications(
                    params={
                        "cursor": cursor,
                        "limit": _DEFAULT_LIKE_PAGE_LIMIT,
                        "reasons": list(_LIKE_REASONS),
                    }
                ),
                description="listing interaction notifications",
            )
        except (
            requests.RequestException,
            TimeoutError,
            atproto_client.exceptions.NetworkError,
        ) as exc:
            print(
                f"{Fore.RED}Failed to fetch interaction notifications: {exc}{Style.RESET_ALL}"
            )
            break

        notifications = get_nested_value(response, "notifications") or []
        page_new_likes, stop_paging = _process_like_page(
            client,
            state,
            notifications,
            cutoff_epoch,
            already_liked,
            dry_run,
            action_delay_seconds,
            summary,
        )
        liked_count += page_new_likes

        # Persist after each page so progress survives an interruption.
        if page_new_likes > 0:
            bot_state.prune_liked_reply_uris(state)
            bot_state.save_state(state, domains="social")

        if stop_paging:
            break

        cursor = get_nested_value(response, "cursor")
        if not cursor:
            break

    bot_state.set_likes_checked_now(state)
    summary["interactions_liked"] = liked_count
    return liked_count


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    controls = get_runtime_controls()
    dry_run = controls["dry_run"]
    action_delay_seconds = controls["action_delay_seconds"]

    if dry_run:
        print(
            f"{Fore.YELLOW}Dry-run mode enabled. Actions will not be executed.{Style.RESET_ALL}"
        )
    if action_delay_seconds > 0:
        print(
            f"{Fore.YELLOW}Action delay enabled: {action_delay_seconds:.2f}s between actions.{Style.RESET_ALL}"
        )

    try:
        print(f"{Fore.YELLOW}Logging in to Bluesky...{Style.RESET_ALL}")
        client, username = login_client()
        print(f"{Fore.GREEN}Successfully logged in.{Style.RESET_ALL}")
    except (
        ValueError,
        requests.RequestException,
        TimeoutError,
        atproto_client.exceptions.NetworkError,
    ) as exc:
        print(f"{Fore.RED}Login failed: {exc}{Style.RESET_ALL}")
        return

    reconciled_blocks = blocks.reconcile_configured_blocks(
        client,
        dry_run=dry_run,
        action_delay_seconds=action_delay_seconds,
    )
    if reconciled_blocks:
        action = "would require" if dry_run else "required"
        print(
            f"{Fore.GREEN}{reconciled_blocks} configured block"
            f"{'s' if reconciled_blocks != 1 else ''} {action} action.{Style.RESET_ALL}"
        )

    state = bot_state.load_state()
    social_summary = {
        "follow_back_candidates": 0,
        "follow_back_added": 0,
        "protected": 0,
        "interaction_candidates": 0,
        "interaction_eligible": 0,
        "interaction_added": 0,
        "interactions_liked": 0,
        "joke_replies": 0,
        "starter_pack_follows": 0,
        "starter_pack_scan_complete": 0,
        "failed": 0,
    }

    try:
        follow_back(
            client,
            dry_run,
            action_delay_seconds,
            social_summary,
            state,
        )
    except (
        ValueError,
        requests.RequestException,
        TimeoutError,
        atproto_client.exceptions.NetworkError,
    ) as exc:
        social_summary["failed"] += 1
        print(f"{Fore.RED}Follow-back failed: {exc}{Style.RESET_ALL}")

    try:
        followed = follow_interactors(
            client, state, dry_run, action_delay_seconds, social_summary
        )
        print(
            f"{Fore.GREEN}Followed {followed} new interactor"
            f"{'s' if followed != 1 else ''}.{Style.RESET_ALL}"
        )
    except (
        ValueError,
        requests.RequestException,
        TimeoutError,
        atproto_client.exceptions.NetworkError,
    ) as exc:
        social_summary["failed"] += 1
        print(f"{Fore.RED}Interaction-follow failed: {exc}{Style.RESET_ALL}")

    attributed_follows = track_starter_pack_follows(
        client, state, dry_run, social_summary
    )

    try:
        replied = reply_to_joke_requests(
            client, username, state, dry_run, social_summary
        )
        print(f"{Fore.GREEN}Replied to {replied} joke request(s).{Style.RESET_ALL}")
    except (
        ValueError,
        requests.RequestException,
        TimeoutError,
        atproto_client.exceptions.NetworkError,
    ) as exc:
        social_summary["failed"] += 1
        print(f"{Fore.RED}Joke-request replies failed: {exc}{Style.RESET_ALL}")
    print(
        f"{Fore.GREEN}Observed {attributed_follows} new starter-pack follow"
        f"{'s' if attributed_follows != 1 else ''}.{Style.RESET_ALL}"
    )

    try:
        liked = like_replies(
            client, state, dry_run, action_delay_seconds, social_summary
        )
        print(
            f"{Fore.GREEN}Liked {liked} new interaction"
            f"{'s' if liked != 1 else ''}.{Style.RESET_ALL}"
        )
    except (
        ValueError,
        requests.RequestException,
        TimeoutError,
        atproto_client.exceptions.NetworkError,
    ) as exc:
        social_summary["failed"] += 1
        print(f"{Fore.RED}Interaction liking failed: {exc}{Style.RESET_ALL}")

    print(_social_summary_line(social_summary, dry_run))
    bot_state.save_state(state, domains="social")
    if social_summary["failed"]:
        raise RuntimeError(
            f"Social run completed with {social_summary['failed']} failed action(s)."
        )
    print(f"{Fore.GREEN}Done.{Style.RESET_ALL}")


if __name__ == "__main__":
    main()
