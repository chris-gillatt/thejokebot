"""Discover explicit joke requests and post idempotent replies."""

from __future__ import annotations

import re
import time
from datetime import datetime

from atproto import models

from thejokebot import config as runtime_config
from thejokebot import denylist as joke_denylist
from thejokebot import providers as joke_providers
from thejokebot import state as bot_state
from thejokebot.commands import post_joke as joke_posting
from thejokebot.runtime import get_nested_value, mask_sensitive, retry_network_call

_CONFIG = runtime_config.get_follows_and_likes_config()["joke_requests"]
_ENABLED = _CONFIG["enabled"]
_PHRASES = tuple(_CONFIG["phrases"])
_MAX_REPLIES = _CONFIG["max_replies"]
_MAX_REPLIES_PER_PERSON = _CONFIG["max_replies_per_person"]
_MAX_PAGES = _CONFIG["max_pages"]
_PAGE_LIMIT = _CONFIG["page_limit"]
_BOOTSTRAP_LOOKBACK_SECONDS = _CONFIG["bootstrap_lookback_seconds"]
_REASONS = ("mention", "reply")


def _notification_epoch(notification):
    indexed_at = get_nested_value(notification, "indexed_at") or get_nested_value(
        notification, "indexedAt"
    )
    if not indexed_at:
        return None
    try:
        return datetime.fromisoformat(indexed_at.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def matches_request(text: str, phrases: tuple[str, ...]) -> bool:
    return any(
        re.search(
            rf"(?<!\w){re.escape(phrase).replace(r'\ ', r'\s+')}(?!\w)",
            text,
            re.IGNORECASE,
        )
        for phrase in phrases
    )


def request_candidate(
    notification,
    username,
    replied_uris,
    cutoff_epoch,
    *,
    upper_epoch=float("inf"),
    boundary_uris: set[str] | frozenset[str] = frozenset(),
    phrases: tuple[str, ...] = _PHRASES,
):
    reason = get_nested_value(notification, "reason")
    uri = get_nested_value(notification, "uri")
    cid = get_nested_value(notification, "cid")
    text = str(get_nested_value(notification, "record", "text") or "")
    if reason not in _REASONS or not uri or not cid:
        return None
    if uri in replied_uris or re.search(r"(?:^|\s)#report\b", text, re.IGNORECASE):
        return None
    notification_epoch = _notification_epoch(notification)
    if notification_epoch is None or notification_epoch > upper_epoch:
        return None
    if notification_epoch < cutoff_epoch:
        return None
    if notification_epoch == cutoff_epoch and uri in boundary_uris:
        return None
    if not matches_request(text, phrases):
        return None
    if reason == "reply" and f"@{username.lower()}" not in text.lower():
        return None
    reply = get_nested_value(notification, "record", "reply")
    root_uri = get_nested_value(reply, "root", "uri") or uri
    root_cid = get_nested_value(reply, "root", "cid") or cid
    return uri, cid, root_uri, root_cid


def select_reply_joke(state, used_b64s=None):
    cutoff = joke_posting.get_current_epoch() - (joke_posting.DAYS_LIMIT * 86400)
    excluded_b64s = joke_denylist.get_denylisted_b64s(joke_denylist.load_denylist())
    excluded_b64s |= used_b64s or set()
    failures = []
    provider_name = joke_providers.FALLBACK_PROVIDER
    try:
        joke, encoded = joke_posting.pick_joke(
            excluded_b64s, provider_name, hashtags=["#joke"]
        )
        return joke, encoded, provider_name, None, failures, cutoff
    except (ValueError, OSError, UnicodeError, TimeoutError) as exc:
        failures.append(
            (provider_name, str(exc), joke_posting._failure_reason_counts(exc))
        )
    raise ValueError("No suitable joke is available for a reply.")


def _reply_tags(state, joke):
    tag_config = runtime_config.get_posting_tag_runtime_config()
    pool = tag_config["tag_pool"]
    shuffled = joke_posting.shuffle_posting_hashtags(
        pool,
        bot_state.get_posting_tag_offset(state),
        tag_config["tag_similarity_groups"],
    )
    tags = joke_posting.fit_hashtags_to_joke(
        joke,
        shuffled,
        tag_config["tag_default"],
        tag_config["tag_fallback"],
        tag_config["tag_max_count"],
        tag_config["tag_similarity_groups"],
    )
    if (
        joke_posting._grapheme_len(joke + "\n\n" + " ".join(tags))
        > joke_posting.BLUESKY_MAX_POST_CHARS
    ):
        raise ValueError("Reply joke exceeds the post length limit with tags.")
    return tags, len(pool)


def _request_has_bot_reply(client, request_uri):
    response = retry_network_call(
        lambda: client.get_post_thread(uri=request_uri, depth=1),
        description=f"checking existing replies to {mask_sensitive(request_uri)}",
    )
    bot_did = get_nested_value(client, "me", "did")
    if (
        not bot_did
        or get_nested_value(response, "thread", "post", "uri") != request_uri
    ):
        raise ValueError("Could not verify the joke request thread before replying.")
    replies = get_nested_value(response, "thread", "replies") or []
    return any(
        get_nested_value(reply, "post", "author", "did") == bot_did for reply in replies
    )


def _collect_notifications(client, cutoff_epoch):
    notifications = []
    cursor = None
    for _ in range(_MAX_PAGES):
        params = {"limit": _PAGE_LIMIT, "reasons": list(_REASONS)}
        if cursor:
            params["cursor"] = cursor
        response = retry_network_call(
            lambda params=params: client.app.bsky.notification.list_notifications(
                params=params
            ),
            description="listing tagged joke requests",
        )
        page = get_nested_value(response, "notifications") or []
        notifications.extend(page)
        reached_checkpoint = any(
            (epoch := _notification_epoch(notification)) is not None
            and epoch < cutoff_epoch
            for notification in page
        )
        cursor = get_nested_value(response, "cursor")
        if reached_checkpoint or not cursor:
            return notifications
    raise ValueError(
        "Joke-request notification scan reached the configured page limit before "
        "the previous checkpoint."
    )


def reply_to_joke_requests(client, username, state, dry_run, summary=None):
    if summary is None:
        summary = {}
    if not _ENABLED:
        summary["joke_replies"] = 0
        return 0
    replied_uris = bot_state.get_replied_joke_request_uris(state)
    upper_epoch = time.time()
    checkpoint, boundary_uris = bot_state.get_joke_request_checkpoint(state)
    cutoff_epoch = (
        checkpoint
        if checkpoint is not None
        else upper_epoch - _BOOTSTRAP_LOOKBACK_SECONDS
    )
    notifications = _collect_notifications(client, cutoff_epoch)
    replied_count = 0
    replies_by_person = {}
    used_b64s = set()
    for notification in sorted(
        notifications,
        key=lambda item: (
            _notification_epoch(item) or 0,
            str(get_nested_value(item, "uri") or ""),
        ),
    ):
        candidate = request_candidate(
            notification,
            username,
            replied_uris,
            cutoff_epoch,
            upper_epoch=upper_epoch,
            boundary_uris=boundary_uris,
        )
        if candidate is None or replied_count >= _MAX_REPLIES:
            continue
        uri, cid, root_uri, root_cid = candidate
        author_did = get_nested_value(notification, "author", "did")
        if (
            not author_did
            or replies_by_person.get(author_did, 0) >= _MAX_REPLIES_PER_PERSON
        ):
            continue
        if dry_run:
            print(f"[DRY-RUN] Would reply with a joke to {mask_sensitive(uri)}")
            replied_count += 1
            replies_by_person[author_did] = replies_by_person.get(author_did, 0) + 1
            continue
        if _request_has_bot_reply(client, uri):
            print(
                "Skipping joke request because the bot has already replied: "
                f"{mask_sensitive(uri)}"
            )
            bot_state.record_replied_joke_request_uri(state, uri)
            replied_uris.add(uri)
            bot_state.prune_replied_joke_request_uris(state)
            bot_state.save_state(state, domains="social")
            continue
        joke, encoded, provider, _starting_provider, failures, _cutoff = (
            select_reply_joke(state, used_b64s)
        )
        tags, pool_size = _reply_tags(state, joke)
        reply_text = f"{joke}\n\n{' '.join(tags)}"
        facets = joke_posting.build_hashtag_facets(joke, tags)
        reply_ref = models.AppBskyFeedPost.ReplyRef(
            parent=models.ComAtprotoRepoStrongRef.Main(uri=uri, cid=cid),
            root=models.ComAtprotoRepoStrongRef.Main(uri=root_uri, cid=root_cid),
        )
        retry_network_call(
            lambda: client.send_post(
                text=reply_text, facets=facets, reply_to=reply_ref
            ),
            description=f"replying to joke request {mask_sensitive(uri)}",
            # A timeout can occur after Bluesky accepts the post. A second write
            # would create another reply; the next run can inspect the thread.
            max_attempts=1,
        )
        for failed_provider, error, reason_counts in failures:
            bot_state.record_failure(
                state, failed_provider, error, reason_counts=reason_counts
            )
        bot_state.advance_posting_tag_offset(state, 1, pool_size)
        used_b64s.add(encoded)
        bot_state.record_replied_joke_request_uri(state, uri)
        replied_uris.add(uri)
        replied_count += 1
        replies_by_person[author_did] = replies_by_person.get(author_did, 0) + 1
        bot_state.prune_replied_joke_request_uris(state)
        bot_state.save_state(state, domains=("posting", "social"))
    if not dry_run:
        upper_boundary_uris = {
            str(get_nested_value(notification, "uri") or "")
            for notification in notifications
            if _notification_epoch(notification) == upper_epoch
        }
        bot_state.set_joke_request_checkpoint(state, upper_epoch, upper_boundary_uris)
        bot_state.save_state(state, domains="social")
    summary["joke_replies"] = replied_count
    return replied_count
