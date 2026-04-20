"""Follow back new followers and like replies to the bot's posts."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone

import requests
from colorama import Fore, Style

import bluesky_state
from bluesky_common import get_runtime_controls, login_client
from bluesky_follower_utils import fetch_paginated_data

_DEFAULT_LIKE_MAX_PAGES = 5
_DEFAULT_LIKE_PAGE_LIMIT = 100
_LIKE_WINDOW_SECONDS = 24 * 60 * 60  # only like replies from the last 24 hours


# ---------------------------------------------------------------------------
# Follow-back
# ---------------------------------------------------------------------------

def follow_back(client, username: str, dry_run: bool, action_delay_seconds: float, unfollowed_dids: set | None = None) -> None:
    """Follow back any followers the bot is not yet following."""
    if unfollowed_dids is None:
        unfollowed_dids = set()
    user_did = client.me.did
    print(f"{Fore.YELLOW}Fetching followers and following for user: {username}{Style.RESET_ALL}")

    followers = fetch_paginated_data(client.get_followers, user_did)
    following = fetch_paginated_data(client.get_follows, user_did)

    follower_dids = {f.did for f in followers}
    following_dids = {f.did for f in following}

    to_follow_back = follower_dids - following_dids
    print(f"{Fore.GREEN}Found {len(to_follow_back)} followers to follow back.{Style.RESET_ALL}")

    for i, did in enumerate(to_follow_back, start=1):
        if did in unfollowed_dids:
            print(
                f"{Fore.GREEN}({i}/{len(to_follow_back)}) Re-engagement: {did} is following again after previous unfollow.{Style.RESET_ALL}"
            )
        print(f"{Fore.YELLOW}({i}/{len(to_follow_back)}) Following {did}...{Style.RESET_ALL}")
        if dry_run:
            print(f"{Fore.YELLOW}[DRY-RUN] Would follow {did}{Style.RESET_ALL}")
        else:
            client.follow(did)
            print(f"{Fore.GREEN}Followed {did}{Style.RESET_ALL}")

        if action_delay_seconds > 0 and i < len(to_follow_back):
            time.sleep(action_delay_seconds)

    print(f"{Fore.GREEN}Follow-back completed.{Style.RESET_ALL}")


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


def like_replies(client, state: dict, dry_run: bool, action_delay_seconds: float) -> int:
    """Like replies to the bot's posts from the last 24 hours.

    Notifications older than _LIKE_WINDOW_SECONDS are skipped. Already-liked
    URIs (tracked in state) are also skipped. State is saved after each page
    so progress survives an interruption.

    Returns the number of new likes performed.
    """
    already_liked = bluesky_state.get_liked_reply_uris(state)
    liked_count = 0
    cutoff_epoch = time.time() - _LIKE_WINDOW_SECONDS

    max_pages = _DEFAULT_LIKE_MAX_PAGES
    page_limit = _DEFAULT_LIKE_PAGE_LIMIT
    cursor = None

    for _ in range(max_pages):
        response = client.app.bsky.notification.list_notifications(
            params={
                "cursor": cursor,
                "limit": page_limit,
                "reasons": ["reply"],
            }
        )

        notifications = _get_value(response, "notifications") or []
        page_new_likes = 0
        stop_paging = False

        for notification in notifications:
            reason = _get_value(notification, "reason")
            if reason != "reply":
                continue

            # Parse indexed_at to epoch for age check.
            indexed_at = _get_value(notification, "indexed_at") or _get_value(notification, "indexedAt")
            if indexed_at:
                try:
                    ts = datetime.fromisoformat(indexed_at.replace("Z", "+00:00"))
                    notification_epoch = ts.timestamp()
                except (ValueError, AttributeError):
                    notification_epoch = None
            else:
                notification_epoch = None

            if notification_epoch is not None and notification_epoch < cutoff_epoch:
                # Notifications are ordered newest-first; once we hit one
                # older than the cutoff the rest will be too.
                stop_paging = True
                break

            uri = _get_value(notification, "uri")
            cid = _get_value(notification, "cid")
            if not uri or not cid:
                continue

            # Never like #report replies — those are handled by the reports workflow.
            reply_text = _get_value(notification, "record", "text") or ""
            if re.search(r"(?:^|\s)#report\b", reply_text, re.IGNORECASE):
                continue

            if uri in already_liked:
                continue

            if dry_run:
                print(f"{Fore.YELLOW}[DRY-RUN] Would like reply: {uri}{Style.RESET_ALL}")
            else:
                try:
                    client.like(uri=uri, cid=cid)
                    print(f"{Fore.GREEN}Liked reply: {uri}{Style.RESET_ALL}")
                except Exception as exc:
                    print(f"{Fore.RED}Failed to like {uri}: {exc}{Style.RESET_ALL}")
                    continue

            bluesky_state.record_liked_reply_uri(state, uri)
            already_liked.add(uri)
            liked_count += 1
            page_new_likes += 1

            if action_delay_seconds > 0:
                time.sleep(action_delay_seconds)

        # Persist after each page so progress survives an interruption.
        if page_new_likes > 0:
            bluesky_state.prune_liked_reply_uris(state)
            bluesky_state.save_state(state)

        if stop_paging:
            break

        cursor = _get_value(response, "cursor")
        if not cursor:
            break

    bluesky_state.set_likes_checked_now(state)
    return liked_count


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    controls = get_runtime_controls()
    dry_run = controls["dry_run"]
    action_delay_seconds = controls["action_delay_seconds"]

    if dry_run:
        print(f"{Fore.YELLOW}Dry-run mode enabled. Actions will not be executed.{Style.RESET_ALL}")
    if action_delay_seconds > 0:
        print(
            f"{Fore.YELLOW}Action delay enabled: {action_delay_seconds:.2f}s between actions.{Style.RESET_ALL}"
        )

    try:
        print(f"{Fore.YELLOW}Logging in to Bluesky...{Style.RESET_ALL}")
        client, username = login_client()
        print(f"{Fore.GREEN}Successfully logged in as {username}.{Style.RESET_ALL}")
    except (ValueError, requests.RequestException, TimeoutError) as exc:
        print(f"{Fore.RED}Login failed: {exc}{Style.RESET_ALL}")
        return

    state = bluesky_state.load_state()
    unfollowed_dids = bluesky_state.get_unfollowed_dids(state)

    try:
        follow_back(client, username, dry_run, action_delay_seconds, unfollowed_dids)
    except (ValueError, requests.RequestException, TimeoutError) as exc:
        print(f"{Fore.RED}Follow-back failed: {exc}{Style.RESET_ALL}")

    try:
        liked = like_replies(client, state, dry_run, action_delay_seconds)
        print(f"{Fore.GREEN}Liked {liked} new repl{'y' if liked == 1 else 'ies'}.{Style.RESET_ALL}")
    except Exception as exc:
        print(f"{Fore.RED}Reply liking failed: {exc}{Style.RESET_ALL}")

    bluesky_state.save_state(state)
    print(f"{Fore.GREEN}Done.{Style.RESET_ALL}")


if __name__ == "__main__":
    main()
