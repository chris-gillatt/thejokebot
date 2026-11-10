"""Like recent replies and reposts of the bot's posts."""

import hashlib
import re
import time
from datetime import datetime, timezone

import atproto_client.exceptions
import requests
from atproto import models
from atproto_client.exceptions import BadRequestError
from colorama import Fore, Style

from thejokebot import config as runtime_config
from thejokebot import state as bot_state
from thejokebot import state_transactions
from thejokebot.runtime import get_nested_value, mask_sensitive, retry_network_call

_CONFIG = runtime_config.get_follows_and_likes_config()
_MAX_PAGES = _CONFIG["like_max_pages"]
_PAGE_LIMIT = _CONFIG["like_page_limit"]
_WINDOW_SECONDS = 24 * 60 * 60
_REASONS = ("reply", "repost")
_UTC_OFFSET = "+00:00"
_LIKE_COLLECTION = "app.bsky.feed.like"
_TID_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"


def _like_rkey(uri):
    digest = hashlib.sha256(uri.encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)
    encoded = ["2"] * 13
    for index in range(12, -1, -1):
        value, digit = divmod(value, len(_TID_ALPHABET))
        encoded[index] = _TID_ALPHABET[digit]
    return "".join(encoded)


def _like_record_at_key(client, repo_did, rkey):
    try:
        return retry_network_call(
            lambda: client.com.atproto.repo.get_record(
                {"repo": repo_did, "collection": _LIKE_COLLECTION, "rkey": rkey}
            ),
            description="reconciling interaction like",
        )
    except BadRequestError as exc:
        if (
            get_nested_value(exc, "response", "status_code") == 400
            and get_nested_value(exc, "response", "content", "error")
            == "RecordNotFound"
        ):
            return None
        raise


def _verify_like_record(receipt, repo_did, rkey, uri, cid):
    expected_uri = f"at://{repo_did}/{_LIKE_COLLECTION}/{rkey}"
    if get_nested_value(receipt, "uri") != expected_uri:
        raise ValueError("Like record receipt does not match its saved key")
    value = get_nested_value(receipt, "value")
    if value is None:
        raise ValueError("Like record receipt has no record value")
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        value = model_dump(by_alias=True, exclude_none=True)
    if not isinstance(value, dict):
        raise ValueError("Like record receipt has an unexpected value")
    subject = value.get("subject")
    if (
        value.get("$type") != _LIKE_COLLECTION
        or not isinstance(subject, dict)
        or subject.get("uri") != uri
        or subject.get("cid") != cid
    ):
        raise ValueError("Like record receipt does not match its saved subject")


def _create_or_reconcile_like(client, uri, cid):
    repo_did = client.me.did
    rkey = _like_rkey(uri)
    existing = _like_record_at_key(client, repo_did, rkey)
    if existing is not None:
        _verify_like_record(existing, repo_did, rkey, uri, cid)
        return

    expected_uri = f"at://{repo_did}/{_LIKE_COLLECTION}/{rkey}"
    record = models.AppBskyFeedLike.Record(
        subject=models.ComAtprotoRepoStrongRef.Main(uri=uri, cid=cid),
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    try:
        receipt = client.app.bsky.feed.like.create(
            repo=repo_did,
            record=record,
            rkey=rkey,
        )
    except Exception as create_error:
        try:
            existing = _like_record_at_key(client, repo_did, rkey)
        except Exception:
            raise create_error
        if existing is None:
            raise
        _verify_like_record(existing, repo_did, rkey, uri, cid)
    else:
        if get_nested_value(receipt, "uri") != expected_uri or not get_nested_value(
            receipt, "cid"
        ):
            raise ValueError("Like record receipt does not match its saved key")


def _parse_notification_epoch(notification):
    indexed_at = get_nested_value(notification, "indexed_at") or get_nested_value(
        notification, "indexedAt"
    )
    if not indexed_at:
        return None
    try:
        return datetime.fromisoformat(indexed_at.replace("Z", _UTC_OFFSET)).timestamp()
    except ValueError, AttributeError:
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
        _create_or_reconcile_like(client, uri, cid)
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
    completed_scan = False

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
            summary["failed"] = summary.get("failed", 0) + 1
            break

        notifications = get_nested_value(response, "notifications") or []
        previous_likes = set(already_liked)
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

        if page_new_likes > 0 and not dry_run:
            _checkpoint_likes(state, already_liked - previous_likes)

        if stop_paging:
            completed_scan = True
            break

        cursor = get_nested_value(response, "cursor")
        if not cursor:
            completed_scan = True
            break

    if not dry_run and completed_scan:
        state_transactions.apply(state, bot_state.set_likes_checked_now)
    summary["interactions_liked"] = liked_count
    return liked_count


def _checkpoint_likes(state, uris):
    def record(latest):
        for uri in sorted(uris):
            bot_state.record_liked_reply_uri(latest, uri)
        bot_state.prune_liked_reply_uris(latest)

    state_transactions.apply(state, record)
