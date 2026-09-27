"""Track follows attributed to Bluesky starter packs."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

import atproto_client.exceptions
import requests
from colorama import Fore, Style

from thejokebot import state as bot_state
from thejokebot.runtime import get_nested_value, retry_network_call

_WINDOW_DAYS = 30
_MAX_PAGES = 20
_PAGE_LIMIT = 100
_UTC_OFFSET = "+00:00"
_URI_PATTERN = re.compile(
    r"^at://(?P<creator>[^/]+)/app\.bsky\.graph\.starterpack/(?P<rkey>[^/]+)$"
)


def _parse_notification_epoch(notification):
    indexed_at = get_nested_value(notification, "indexed_at") or get_nested_value(
        notification, "indexedAt"
    )
    if not indexed_at:
        return None
    try:
        return datetime.fromisoformat(indexed_at.replace("Z", _UTC_OFFSET)).timestamp()
    except (ValueError, AttributeError):
        return None


def _starter_pack_observation(notification) -> dict | None:
    """Return public pack metadata for an attributed follow notification."""
    if get_nested_value(notification, "reason") != "follow":
        return None
    starter_pack = get_nested_value(notification, "starter_pack") or get_nested_value(
        notification, "starterPack"
    )
    pack_uri = str(get_nested_value(starter_pack, "uri") or "").strip()
    if not _URI_PATTERN.fullmatch(pack_uri):
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


def _update_page_boundary(
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


def _record_observation(
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


def _process_page(
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
        _update_page_boundary(
            notification, notification_epoch, notification_hash, page_state
        )
        if notification_epoch < stop_epoch:
            return True
        _record_observation(
            notification,
            notification_epoch,
            notification_hash,
            stop_epoch,
            previous_boundary_hashes,
            page_state,
        )
    return False


def _collect_attribution(client, state: dict, now: datetime) -> dict | None:
    """Collect a complete incremental scan of starter-pack follow attribution."""
    attribution = bot_state.get_starter_pack_attribution(state)
    high_water = attribution.get("high_water_indexed_at")
    previous_boundary_hashes = set(attribution.get("boundary_notification_hashes", []))
    bootstrap_cutoff = now - timedelta(days=_WINDOW_DAYS)
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

    for _ in range(_MAX_PAGES):
        try:
            response = retry_network_call(
                lambda current_cursor=cursor: (
                    client.app.bsky.notification.list_notifications(
                        params={
                            "cursor": current_cursor,
                            "limit": _PAGE_LIMIT,
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

        complete = _process_page(
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
    scan = _collect_attribution(client, state, datetime.now(timezone.utc))
    summary["starter_pack_scan_complete"] = int(scan is not None)
    if scan is None:
        summary["starter_pack_follows"] = 0
        return 0
    count = len(scan["observations"])
    summary["starter_pack_follows"] = count
    if not dry_run:
        bot_state.record_starter_pack_attribution_scan(state, **scan)
    return count
