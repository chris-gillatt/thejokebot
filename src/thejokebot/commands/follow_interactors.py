"""Follow recent users who interact with the bot's posts."""

from __future__ import annotations

import time
from datetime import datetime

import atproto_client.exceptions
import requests
from colorama import Fore, Style

from thejokebot import config as runtime_config
from thejokebot import state as bot_state
from thejokebot.followers import fetch_paginated_data
from thejokebot.runtime import get_nested_value, mask_sensitive, retry_network_call

_CONFIG = runtime_config.get_follows_and_likes_config()
_REASONS = ("reply", "repost", "like")
_WINDOW_SECONDS = 24 * 60 * 60
_MAX_PAGES = _CONFIG["interaction_follow_max_pages"]
_PAGE_LIMIT = _CONFIG["interaction_follow_page_limit"]
_FOLLOW_PAGE_LIMIT = 100
_FOLLOW_MAX_PAGES = 100
_FOLLOW_MAX_RUNTIME_SECONDS = 120
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


def _collect_page_interactor_dids(
    notifications, user_did, cutoff_epoch, interactor_dids
):
    for notification in notifications:
        reason = get_nested_value(notification, "reason")
        if reason not in _REASONS:
            continue

        notification_epoch = _parse_notification_epoch(notification)
        if notification_epoch is not None and notification_epoch < cutoff_epoch:
            return True

        author_did = get_nested_value(notification, "author", "did")
        if author_did and author_did != user_did:
            interactor_dids.add(author_did)
    return False


def _collect_interactor_dids(client, user_did, cutoff_epoch):
    interactor_dids: set[str] = set()
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

        notifications = get_nested_value(response, "notifications") or []
        if _collect_page_interactor_dids(
            notifications, user_did, cutoff_epoch, interactor_dids
        ):
            break

        cursor = get_nested_value(response, "cursor")
        if not cursor:
            break

    return interactor_dids


def _follow_did_list(client, state, to_follow, dry_run, action_delay_seconds):
    followed_count = 0
    for index, did in enumerate(to_follow, start=1):
        masked_did = mask_sensitive(did)
        print(
            f"{Fore.YELLOW}({index}/{len(to_follow)}) Following interactor "
            f"{masked_did}...{Style.RESET_ALL}"
        )
        if dry_run:
            print(
                f"{Fore.YELLOW}[DRY-RUN] Would follow interactor "
                f"{masked_did}{Style.RESET_ALL}"
            )
            followed_count += 1
        else:
            try:
                retry_network_call(
                    lambda current_did=did: client.follow(current_did),
                    description=f"following interactor {masked_did}",
                )
                print(f"{Fore.GREEN}Followed interactor {masked_did}{Style.RESET_ALL}")
                bot_state.record_follow_grace(state, did, source="interaction")
                bot_state.record_acquisition(state, did, "interaction")
                followed_count += 1
            except (
                requests.RequestException,
                TimeoutError,
                atproto_client.exceptions.NetworkError,
            ) as exc:
                print(
                    f"{Fore.RED}Failed to follow interactor {masked_did}: "
                    f"{exc}{Style.RESET_ALL}"
                )
                continue

        if action_delay_seconds > 0 and index < len(to_follow):
            time.sleep(action_delay_seconds)

    return followed_count


def follow_interactors(
    client,
    state: dict,
    dry_run: bool,
    action_delay_seconds: float,
    summary: dict | None = None,
) -> int:
    """Follow users who interacted with the bot's posts in the last 24 hours."""
    user_did = client.me.did
    if summary is None:
        summary = {}
    grace_dids = bot_state.get_follow_grace_dids(state)
    unfollowed_dids = bot_state.get_unfollowed_dids(state)

    print(
        f"{Fore.YELLOW}Fetching current follows for interaction-follow check.{Style.RESET_ALL}"
    )
    following = fetch_paginated_data(
        client.get_follows,
        actor=user_did,
        limit=_FOLLOW_PAGE_LIMIT,
        max_pages=_FOLLOW_MAX_PAGES,
        max_runtime_seconds=_FOLLOW_MAX_RUNTIME_SECONDS,
        require_complete=True,
    )
    already_following = {profile.did for profile in following}

    cutoff_epoch = time.time() - _WINDOW_SECONDS
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
        f"{Fore.YELLOW}Found {len(interactor_dids)} unique interactor(s) in the last "
        f"24 hours, {len(to_follow)} new to follow.{Style.RESET_ALL}"
    )

    followed_count = _follow_did_list(
        client, state, to_follow, dry_run, action_delay_seconds
    )
    summary["interaction_added"] = followed_count
    summary["failed"] = summary.get("failed", 0) + len(to_follow) - followed_count

    if followed_count > 0 and not dry_run:
        bot_state.prune_follow_grace(state)

    print(f"{Fore.GREEN}Interaction-follow completed.{Style.RESET_ALL}")
    return followed_count
