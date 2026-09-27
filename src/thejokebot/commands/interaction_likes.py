"""Like recent replies and reposts of the bot's posts."""

from __future__ import annotations

import re
import time
from datetime import datetime

import atproto_client.exceptions
import requests
from colorama import Fore, Style

from thejokebot import config as runtime_config
from thejokebot import state as bot_state
from thejokebot.runtime import get_nested_value, mask_sensitive, retry_network_call

_CONFIG = runtime_config.get_follows_and_likes_config()
_MAX_PAGES = _CONFIG["like_max_pages"]
_PAGE_LIMIT = _CONFIG["like_page_limit"]
_WINDOW_SECONDS = 24 * 60 * 60
_REASONS = ("reply", "repost")
_UTC_OFFSET = "+00:00"


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


def _like_candidate(notification, cutoff_epoch, already_liked):
    reason = get_nested_value(notification, "reason")
    if reason not in _REASONS:
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


def _process_page(
    client,
    state,
    notifications,
    cutoff_epoch,
    already_liked,
    dry_run,
    action_delay_seconds,
    summary,
):
    """Process one page of notifications, liking applicable items."""
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
    """Like replies and reposts of the bot's posts from the last 24 hours."""
    already_liked = bot_state.get_liked_reply_uris(state)
    if summary is None:
        summary = {}
    liked_count = 0
    cutoff_epoch = time.time() - _WINDOW_SECONDS
    cursor = None

    for _ in range(_MAX_PAGES):
        try:
            response = retry_network_call(
                lambda: client.app.bsky.notification.list_notifications(
                    params={
                        "cursor": cursor,
                        "limit": _PAGE_LIMIT,
                        "reasons": list(_REASONS),
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
        page_new_likes, stop_paging = _process_page(
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
