"""Follow back new followers and like reply/repost interactions."""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timedelta, timezone

import requests
import atproto_client.exceptions
from colorama import Fore, Style

import bluesky_blocks
import bluesky_config
import bluesky_state
from bluesky_common import (
    get_runtime_controls,
    login_client,
    mask_sensitive,
    retry_network_call,
)
from bluesky_follower_utils import fetch_paginated_data

_FOLLOWS_AND_LIKES_CONFIG = bluesky_config.get_follows_and_likes_config()

_DEFAULT_LIKE_MAX_PAGES = _FOLLOWS_AND_LIKES_CONFIG["like_max_pages"]
_DEFAULT_LIKE_PAGE_LIMIT = _FOLLOWS_AND_LIKES_CONFIG["like_page_limit"]
_LIKE_WINDOW_SECONDS = 24 * 60 * 60  # only like replies from the last 24 hours
_LIKE_REASONS = ("reply", "repost")
_UTC_OFFSET = "+00:00"

_INTERACTION_FOLLOW_REASONS = ("reply", "repost", "like")
_INTERACTION_WINDOW_SECONDS = (
    24 * 60 * 60
)  # only follow interactors from the last 24 hours
_INTERACTION_FOLLOW_MAX_PAGES = _FOLLOWS_AND_LIKES_CONFIG[
    "interaction_follow_max_pages"
]
_INTERACTION_FOLLOW_PAGE_LIMIT = _FOLLOWS_AND_LIKES_CONFIG[
    "interaction_follow_page_limit"
]
_FOLLOW_BACK_PAGE_LIMIT = 100
_FOLLOW_BACK_MAX_PAGES = 1000
_FOLLOW_BACK_MAX_RUNTIME_SECONDS = 180
_FOLLOW_BACK_MAX_RECONCILIATION_PASSES = 3
_FOLLOW_BACK_SETTLE_SECONDS = 5
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
    "starter_pack_follows",
    "starter_pack_scan_complete",
    "failed",
)


def _social_summary_line(summary: dict, dry_run: bool) -> str:
    counts = ", ".join(
        f"{field}={int(summary.get(field) or 0)}" for field in _SOCIAL_SUMMARY_FIELDS
    )
    return f"Social summary: {counts}, dry_run={'true' if dry_run else 'false'}."


def _follow_back_candidates(
    client,
    state,
    to_follow_back,
    dry_run,
    action_delay_seconds,
    attempted_dids,
    summary,
):
    for index, did in enumerate(to_follow_back, start=1):
        attempted_dids.add(did)
        masked_did = mask_sensitive(did)
        print(
            f"{Fore.YELLOW}({index}/{len(to_follow_back)}) Following {masked_did}...{Style.RESET_ALL}"
        )
        if dry_run:
            print(f"{Fore.YELLOW}[DRY-RUN] Would follow {masked_did}{Style.RESET_ALL}")
            summary["follow_back_added"] += 1
        else:
            try:
                retry_network_call(
                    lambda current_did=did: client.follow(current_did),
                    description=f"following back {masked_did}",
                )
                print(f"{Fore.GREEN}Followed {masked_did}{Style.RESET_ALL}")
                if state is not None:
                    bluesky_state.record_acquisition(state, did, "followback")
                summary["follow_back_added"] += 1
            except (
                requests.RequestException,
                TimeoutError,
                atproto_client.exceptions.NetworkError,
            ) as exc:
                print(
                    f"{Fore.RED}Failed to follow {masked_did}: {exc}{Style.RESET_ALL}"
                )
                summary["failed"] += 1

        if action_delay_seconds > 0 and index < len(to_follow_back):
            time.sleep(action_delay_seconds)


# ---------------------------------------------------------------------------
# Follow-back
# ---------------------------------------------------------------------------


def follow_back(
    client,
    username: str,
    dry_run: bool,
    action_delay_seconds: float,
    summary: dict | None = None,
    state: dict | None = None,
) -> None:
    """Follow back any followers the bot is not yet following.

    Every current follower is followed back unconditionally.  The unfollow
    history is intentionally NOT consulted here: if someone has re-followed
    the bot they have shown fresh intent to engage and deserve a follow-back
    regardless of prior churn.  Unfollow-history protection applies only to
    proactive follows (see ``follow_interactors``).
    """
    if summary is None:
        summary = {}
    user_did = client.me.did
    print(
        f"{Fore.YELLOW}Fetching followers and following for account.{Style.RESET_ALL}"
    )

    attempted_dids: set[str] = set()
    observed_candidate_dids: set[str] = set()
    cohorts_reconciled = False
    summary["follow_back_candidates"] = 0
    summary["follow_back_added"] = 0
    summary["failed"] = 0

    for pass_number in range(1, _FOLLOW_BACK_MAX_RECONCILIATION_PASSES + 2):
        followers = fetch_paginated_data(
            client.get_followers,
            actor=user_did,
            limit=_FOLLOW_BACK_PAGE_LIMIT,
            max_pages=_FOLLOW_BACK_MAX_PAGES,
            max_runtime_seconds=_FOLLOW_BACK_MAX_RUNTIME_SECONDS,
            require_complete=True,
        )
        following = fetch_paginated_data(
            client.get_follows,
            actor=user_did,
            limit=_FOLLOW_BACK_PAGE_LIMIT,
            max_pages=_FOLLOW_BACK_MAX_PAGES,
            max_runtime_seconds=_FOLLOW_BACK_MAX_RUNTIME_SECONDS,
            require_complete=True,
        )
        follower_dids = {f.did for f in followers}
        following_dids = {f.did for f in following}
        if state is not None and not dry_run and not cohorts_reconciled:
            bluesky_state.reconcile_acquisition_cohorts(state, follower_dids)
            cohorts_reconciled = True
        remaining_dids = follower_dids - following_dids
        observed_candidate_dids |= remaining_dids
        summary["follow_back_candidates"] = len(observed_candidate_dids)

        if not remaining_dids:
            print(
                f"{Fore.GREEN}Verified that all actionable followers are followed back.{Style.RESET_ALL}"
            )
            print(f"{Fore.GREEN}Follow-back completed.{Style.RESET_ALL}")
            return

        if pass_number > _FOLLOW_BACK_MAX_RECONCILIATION_PASSES:
            summary["failed"] += len(remaining_dids)
            raise RuntimeError(
                "Follow-back did not converge after "
                f"{_FOLLOW_BACK_MAX_RECONCILIATION_PASSES} reconciliation passes; "
                f"{len(remaining_dids)} actionable follower(s) remain."
            )

        to_follow_back = sorted(remaining_dids - attempted_dids)
        print(
            f"{Fore.GREEN}Follow-back pass {pass_number}: found "
            f"{len(remaining_dids)} actionable follower(s), "
            f"{len(to_follow_back)} not yet attempted.{Style.RESET_ALL}"
        )
        _follow_back_candidates(
            client,
            state,
            to_follow_back,
            dry_run,
            action_delay_seconds,
            attempted_dids,
            summary,
        )

        if dry_run:
            print(f"{Fore.GREEN}Follow-back dry run completed.{Style.RESET_ALL}")
            return

        time.sleep(_FOLLOW_BACK_SETTLE_SECONDS)


# ---------------------------------------------------------------------------
# Follow interactors
# ---------------------------------------------------------------------------


def _parse_notification_epoch(notification):
    """Parse the indexed_at field of a notification into a Unix timestamp, or None."""
    indexed_at = _get_value(notification, "indexed_at") or _get_value(
        notification, "indexedAt"
    )
    if not indexed_at:
        return None
    try:
        ts = datetime.fromisoformat(indexed_at.replace("Z", _UTC_OFFSET))
        return ts.timestamp()
    except (ValueError, AttributeError):
        return None


def _collect_page_interactor_dids(
    notifications, user_did, cutoff_epoch, interactor_dids
):
    for notification in notifications:
        reason = _get_value(notification, "reason")
        if reason not in _INTERACTION_FOLLOW_REASONS:
            continue

        notification_epoch = _parse_notification_epoch(notification)
        if notification_epoch is not None and notification_epoch < cutoff_epoch:
            return True

        author_did = _get_value(notification, "author", "did")
        if author_did and author_did != user_did:
            interactor_dids.add(author_did)
    return False


def _collect_interactor_dids(client, user_did, cutoff_epoch):
    """Page through interaction notifications; return unique author DIDs within the cutoff."""
    interactor_dids: set[str] = set()
    cursor = None

    for _ in range(_INTERACTION_FOLLOW_MAX_PAGES):
        try:
            response = retry_network_call(
                lambda: client.app.bsky.notification.list_notifications(
                    params={
                        "cursor": cursor,
                        "limit": _INTERACTION_FOLLOW_PAGE_LIMIT,
                        "reasons": list(_INTERACTION_FOLLOW_REASONS),
                    }
                ),
                description="listing interaction notifications for follow",
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

        notifications = _get_value(response, "notifications") or []
        if _collect_page_interactor_dids(
            notifications, user_did, cutoff_epoch, interactor_dids
        ):
            break

        cursor = _get_value(response, "cursor")
        if not cursor:
            break

    return interactor_dids


def _follow_did_list(client, state, to_follow, dry_run, action_delay_seconds):
    """Follow each DID in to_follow; return the count of follows performed."""
    followed_count = 0
    for i, did in enumerate(to_follow, start=1):
        masked_did = mask_sensitive(did)
        print(
            f"{Fore.YELLOW}({i}/{len(to_follow)}) Following interactor {masked_did}...{Style.RESET_ALL}"
        )
        if dry_run:
            print(
                f"{Fore.YELLOW}[DRY-RUN] Would follow interactor {masked_did}{Style.RESET_ALL}"
            )
            followed_count += 1
        else:
            try:
                retry_network_call(
                    lambda current_did=did: client.follow(current_did),
                    description=f"following interactor {masked_did}",
                )
                print(f"{Fore.GREEN}Followed interactor {masked_did}{Style.RESET_ALL}")
                bluesky_state.record_follow_grace(state, did, source="interaction")
                bluesky_state.record_acquisition(state, did, "interaction")
                followed_count += 1
            except (
                requests.RequestException,
                TimeoutError,
                atproto_client.exceptions.NetworkError,
            ) as exc:
                print(
                    f"{Fore.RED}Failed to follow interactor {masked_did}: {exc}{Style.RESET_ALL}"
                )
                continue

        if action_delay_seconds > 0 and i < len(to_follow):
            time.sleep(action_delay_seconds)

    return followed_count


def follow_interactors(
    client,
    state: dict,
    dry_run: bool,
    action_delay_seconds: float,
    summary: dict | None = None,
) -> int:
    """Follow users who have interacted with the bot's posts in the last 24 hours.

    Notifications of type reply, repost, and like are considered. Interactors
    who are already being followed, still within the follow-grace window, or
    who appear in the unfollow history are skipped to prevent repeated
    follow/unfollow churn.

    Followed DIDs are recorded in follow_grace (source="interaction") so that
    the unfollow script respects the standard grace window before unfollowing.

    Returns the number of new follows performed.
    """
    user_did = client.me.did
    if summary is None:
        summary = {}
    grace_dids = bluesky_state.get_follow_grace_dids(state)
    unfollowed_dids = bluesky_state.get_unfollowed_dids(state)

    print(
        f"{Fore.YELLOW}Fetching current follows for interaction-follow check.{Style.RESET_ALL}"
    )
    following = fetch_paginated_data(
        client.get_follows,
        actor=user_did,
        limit=_FOLLOW_BACK_PAGE_LIMIT,
        max_pages=_FOLLOW_BACK_MAX_PAGES,
        max_runtime_seconds=_FOLLOW_BACK_MAX_RUNTIME_SECONDS,
        require_complete=True,
    )
    already_following = {f.did for f in following}

    cutoff_epoch = time.time() - _INTERACTION_WINDOW_SECONDS
    interactor_dids = _collect_interactor_dids(client, user_did, cutoff_epoch)

    existing_skips = interactor_dids & already_following
    remaining = interactor_dids - existing_skips
    grace_skips = remaining & grace_dids
    remaining -= grace_skips
    history_skips = remaining & unfollowed_dids
    to_follow = sorted(remaining - history_skips)
    summary["interaction_candidates"] = len(interactor_dids)
    summary["interaction_eligible"] = len(to_follow)
    summary["protected"] = summary.get("protected", 0) + len(
        existing_skips | grace_skips | history_skips
    )

    print(
        f"{Fore.YELLOW}Found {len(interactor_dids)} unique interactor(s) in the last 24 hours, "
        f"{len(to_follow)} new to follow.{Style.RESET_ALL}"
    )

    followed_count = _follow_did_list(
        client, state, to_follow, dry_run, action_delay_seconds
    )
    summary["interaction_added"] = followed_count
    summary["failed"] = summary.get("failed", 0) + len(to_follow) - followed_count

    if followed_count > 0 and not dry_run:
        bluesky_state.prune_follow_grace(state)

    print(f"{Fore.GREEN}Interaction-follow completed.{Style.RESET_ALL}")
    return followed_count


# ---------------------------------------------------------------------------
# Reply likes
# ---------------------------------------------------------------------------


def _get_value(obj, *path):
    cur = obj
    for key in path:
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            cur = getattr(cur, key, None)
    return cur


# ---------------------------------------------------------------------------
# Starter-pack attribution
# ---------------------------------------------------------------------------


def _starter_pack_observation(notification) -> dict | None:
    """Return public pack metadata for an attributed follow notification."""
    if _get_value(notification, "reason") != "follow":
        return None
    starter_pack = _get_value(notification, "starter_pack") or _get_value(
        notification, "starterPack"
    )
    pack_uri = str(_get_value(starter_pack, "uri") or "").strip()
    if not _STARTER_PACK_URI_PATTERN.fullmatch(pack_uri):
        return None
    indexed_at = _get_value(notification, "indexed_at") or _get_value(
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
        "name": str(_get_value(starter_pack, "record", "name") or "Starter pack"),
        "creator_handle": str(_get_value(starter_pack, "creator", "handle") or ""),
        "observed_at": observed_at.isoformat().replace(_UTC_OFFSET, "Z"),
        "date": observed_at.date().isoformat(),
    }


def _notification_hash(notification) -> str:
    uri = str(_get_value(notification, "uri") or "")
    return hashlib.sha256(uri.encode("utf-8")).hexdigest() if uri else ""


def _update_starter_pack_page_boundary(
    notification, notification_epoch, notification_hash, page_state
):
    indexed_at = _get_value(notification, "indexed_at") or _get_value(
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
    attribution = bluesky_state.get_starter_pack_attribution(state)
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
            _get_value(response, "notifications") or [],
            stop_epoch,
            previous_boundary_hashes,
            page_state,
        )

        if complete:
            break
        next_cursor = _get_value(response, "cursor")
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
            now - timedelta(days=bluesky_state.STARTER_PACK_ATTRIBUTION_RETENTION_DAYS)
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
        bluesky_state.record_starter_pack_attribution_scan(state, **scan)
    return count


def _like_candidate(notification, cutoff_epoch, already_liked):
    reason = _get_value(notification, "reason")
    if reason not in _LIKE_REASONS:
        return None, False
    notification_epoch = _parse_notification_epoch(notification)
    if notification_epoch is not None and notification_epoch < cutoff_epoch:
        return None, True
    uri = _get_value(notification, "uri")
    cid = _get_value(notification, "cid")
    if not uri or not cid:
        return None, False
    reply_text = _get_value(notification, "record", "text") or ""
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

        bluesky_state.record_liked_reply_uri(state, uri)
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
    already_liked = bluesky_state.get_liked_reply_uris(state)
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

        notifications = _get_value(response, "notifications") or []
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
            bluesky_state.prune_liked_reply_uris(state)
            bluesky_state.save_state(state, domains="social")

        if stop_paging:
            break

        cursor = _get_value(response, "cursor")
        if not cursor:
            break

    bluesky_state.set_likes_checked_now(state)
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

    reconciled_blocks = bluesky_blocks.reconcile_configured_blocks(
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

    state = bluesky_state.load_state()
    social_summary = {
        "follow_back_candidates": 0,
        "follow_back_added": 0,
        "protected": 0,
        "interaction_candidates": 0,
        "interaction_eligible": 0,
        "interaction_added": 0,
        "interactions_liked": 0,
        "starter_pack_follows": 0,
        "starter_pack_scan_complete": 0,
        "failed": 0,
    }

    try:
        follow_back(
            client,
            username,
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
    bluesky_state.save_state(state, domains="social")
    if social_summary["failed"]:
        raise RuntimeError(
            f"Social run completed with {social_summary['failed']} failed action(s)."
        )
    print(f"{Fore.GREEN}Done.{Style.RESET_ALL}")


if __name__ == "__main__":
    main()
