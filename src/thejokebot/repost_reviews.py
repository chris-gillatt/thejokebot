"""Discover repost suggestions and execute exact, explicitly approved reviews."""

import copy
import hashlib
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import requests
from atproto_client.exceptions import AtProtocolError, BadRequestError

from thejokebot import config, content_creators, state_transactions
from thejokebot.runtime import (
    get_nested_value,
    get_runtime_controls,
    retry_network_call,
)

COLLECTION = "app.bsky.feed.repost"
MAX_CANDIDATES = 5
REVIEW_WINDOW_DAYS = 7
REVIEW_EXPIRY_DAYS = 7
MAX_SOURCE_ACCOUNTS = 50
SOURCE_FEED_LIMIT = 20
MAX_RUNTIME_SECONDS = 180
UNCERTAIN_STATUSES = {"publishing", "removing", "uncertain"}
POST_URI = re.compile(
    r"at://(did:[a-z0-9]+:[^/\s?#]+)/app\.bsky\.feed\.post/([A-Za-z0-9._~:-]+)"
)
HANDLE = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
HASHTAG = re.compile(r"(?<![\w/#])#(\w+)")
DO_NOT_REPOST = re.compile(
    r"(?<!\w)(?:do[\s_-]*not|don['\u2019]?t|no)[\s_-]*repost(?:s|ing)?(?!\w)",
    re.IGNORECASE,
)


class UnavailableContextError(ValueError):
    pass


def utc_now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError("Repost times must include a timezone")
    return value.astimezone(timezone.utc)


def timestamp(value: str) -> datetime:
    return utc_now(datetime.fromisoformat(value.replace("Z", "+00:00")))


def as_dict(value) -> dict:
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        value = dump(by_alias=True, exclude_none=True)
    if not isinstance(value, dict):
        raise ValueError("Unexpected repost API object")
    return value


def _read(operation, deadline: float, description: str):
    def fetch():
        content_creators._check_deadline(deadline)
        return operation()

    result = retry_network_call(fetch, description=description)
    content_creators._check_deadline(deadline)
    return result


def _posts(client, uris: list[str], deadline: float) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for start in range(0, len(uris), 25):
        batch = uris[start : start + 25]
        response = _read(
            lambda: client.get_posts(uris=batch), deadline, "reading repost subjects"
        )
        posts = get_nested_value(response, "posts")
        if not isinstance(posts, list):
            raise ValueError("Repost subject response has no posts list")
        for raw in posts:
            post = as_dict(raw)
            if post.get("uri") not in batch or post["uri"] in result:
                raise ValueError("Repost subject response has unexpected posts")
            result[post["uri"]] = post
    return result


def _images(embed: dict) -> list[dict]:
    images = []
    for image in embed.get("images", []):
        url = image.get("fullsize")
        parsed = urlsplit(url) if isinstance(url, str) else None
        if (
            parsed is None
            or parsed.scheme != "https"
            or parsed.netloc != "cdn.bsky.app"
            or not isinstance(image.get("alt", ""), str)
        ):
            raise ValueError("Unexpected repost image resource")
        images.append({"url": url, "alt": image.get("alt", "")})
    return images


def preview_post(raw) -> dict:
    post = as_dict(raw)
    uri = post.get("uri")
    match = POST_URI.fullmatch(uri) if isinstance(uri, str) else None
    author = post.get("author", {})
    record = post.get("record", {})
    handle = author.get("handle")
    if (
        match is None
        or author.get("did") != match.group(1)
        or not isinstance(handle, str)
        or not HANDLE.fullmatch(handle)
        or not isinstance(post.get("cid"), str)
        or not post["cid"]
        or not isinstance(record.get("text"), str)
    ):
        raise ValueError("Invalid repost subject identity or content")
    embed = post.get("embed") or {}
    images = _images(embed)
    kind = "image" if images else "text"
    if embed and embed.get("$type") != "app.bsky.embed.images#view":
        kind = "unsupported"
    return {
        "uri": uri,
        "cid": post["cid"],
        "author_did": author["did"],
        "handle": handle,
        "text": record["text"],
        "images": images,
        "kind": kind,
        "is_reply": bool(record.get("reply")),
    }


def _moderated(post: dict) -> bool:
    author_viewer = post.get("author", {}).get("viewer") or {}
    excluded = any(
        author_viewer.get(field)
        for field in ("blocking", "blockedBy", "blockingByList", "muted", "mutedByList")
    )
    labelled = any(not label.get("neg") for label in post.get("labels") or [])
    return bool(excluded or labelled)


def _available(post: dict) -> bool:
    viewer = post.get("viewer")
    if not isinstance(viewer, dict):
        raise ValueError("Authenticated repost status is unavailable")
    if viewer.get("repost") or _moderated(post):
        print(
            "Repost candidate skipped: existing repost, moderation or account exclusion."
        )
        return False
    return True


def _context(client, post: dict, deadline: float) -> list[dict]:
    reply = post.get("record", {}).get("reply") or {}
    refs = (
        {reply[field]["uri"]: reply[field]["cid"] for field in ("root", "parent")}
        if reply
        else {}
    )
    if any(not POST_URI.fullmatch(uri) for uri in refs):
        raise ValueError("Invalid repost thread reference")
    parents = _posts(client, list(refs), deadline)
    if set(parents) != set(refs) or any(
        parents[uri].get("cid") != cid for uri, cid in refs.items()
    ):
        raise UnavailableContextError("Repost thread context is missing or changed")
    if any(_moderated(parent) for parent in parents.values()):
        raise UnavailableContextError("Repost thread context is moderated or excluded")
    return [preview_post(parent) for parent in parents.values()]


def read_inventory(client, now: datetime | None = None, *, deadline=None) -> dict:
    reference_time = utc_now(now) if now is not None else None
    deadline = deadline or time.monotonic() + MAX_RUNTIME_SECONDS
    entries: dict[str, dict] = {}
    for raw, author_did in content_creators.iter_interactions(
        client, client.me.did, COLLECTION, deadline
    ):
        record = as_dict(raw)
        value = as_dict(record["value"])
        subject = value["subject"]
        if not POST_URI.fullmatch(subject["uri"]):
            raise ValueError("Repost inventory contains a non-post subject")
        created_at = timestamp(value["createdAt"])
        if created_at > utc_now(reference_time):
            raise ValueError("Repost inventory has a future creation time")
        entries[subject["uri"]] = {
            "post_uri": subject["uri"],
            "repost_uri": record["uri"],
            "repost_cid": record["cid"],
            "subject_cid": subject["cid"],
            "author_did": author_did,
            "created_at": created_at.isoformat(),
            "handle": None,
            "kind": "unknown",
            "is_reply": None,
        }
    posts = _posts(client, list(entries), deadline)
    for uri, post in posts.items():
        preview = preview_post(post)
        for field in ("handle", "kind", "is_reply"):
            entries[uri][field] = preview[field]
    missing = len(entries) - len(posts)
    if missing:
        print(
            f"Repost inventory: {missing} subjects unavailable; format remains unknown."
        )
    return {
        "collected_at": utc_now(reference_time).isoformat(),
        "entries": list(entries.values()),
    }


def _post_tags(record: dict) -> set[str]:
    tags = set(HASHTAG.findall(record["text"]))
    tags.update(record.get("tags") or [])
    for facet in record.get("facets") or []:
        tags.update(
            feature["tag"]
            for feature in facet["features"]
            if feature.get("$type") == "app.bsky.richtext.facet#tag"
        )
    return {tag.casefold() for tag in tags}


def _relevant(post: dict, preview: dict, now, tags, max_age_days) -> bool:
    record = post["record"]
    created_at = timestamp(record["createdAt"])
    post_tags = _post_tags(record)
    searchable = "\n".join(
        [record["text"]]
        + [image["alt"] for image in preview["images"]]
        + list(post_tags)
    )
    if (
        preview["is_reply"]
        or not now - timedelta(days=max_age_days) <= created_at <= now
        or not post_tags.intersection(tags)
        or DO_NOT_REPOST.search(searchable)
    ):
        print("Repost candidate skipped: age, reply, humour tags or no-repost request.")
        return False
    return True


def _candidate(client, post, now, deadline, tags, max_age_days) -> dict | None:
    preview = preview_post(post)
    if not _relevant(post, preview, now, tags, max_age_days):
        return None
    if not _available(post) or preview["kind"] == "unsupported":
        print("Repost candidate skipped: ineligible or unsupported format.")
        return None
    try:
        context = _context(client, post, deadline)
    except UnavailableContextError as exc:
        print(f"Repost candidate skipped: {exc}.")
        return None
    return {
        "key": hashlib.sha256(preview["uri"].encode()).hexdigest(),
        "action": "repost",
        "post": preview,
        "context": context,
        "queued_at": now.isoformat(),
        "expires_at": (now + timedelta(days=REVIEW_EXPIRY_DAYS)).isoformat(),
        "status": "proposed",
    }


def _author_posts(client, author, deadline):
    try:
        response = _read(
            lambda: client.get_author_feed(
                actor=author,
                filter="posts_no_replies",
                limit=SOURCE_FEED_LIMIT,
                include_pins=False,
            ),
            deadline,
            "reading a repost source",
        )
    except BadRequestError as exc:
        error = get_nested_value(exc, "response", "content", "error")
        missing = (
            error == "InvalidRequest"
            and get_nested_value(exc, "response", "content", "message")
            == "Profile not found"
        )
        if get_nested_value(exc, "response", "status_code") != 400 or (
            error not in {"BlockedActor", "BlockedByActor"} and not missing
        ):
            raise
        print(
            "Repost source skipped: Bluesky reports an unavailable or blocked profile."
        )
        return []
    feed = get_nested_value(response, "feed")
    if not isinstance(feed, list):
        raise ValueError("Repost source response has no feed list")
    posts = []
    for raw in feed:
        item = as_dict(raw)
        post = item.get("post", {})
        if item.get("reason"):
            continue
        if post.get("author", {}).get("did") != author:
            raise ValueError("Repost source feed returned another author's original")
        posts.append(post)
    return posts


def _tag_posts(client, tag, now, max_age_days, deadline):
    response = _read(
        lambda: client.app.bsky.feed.search_posts(
            {
                "q": f"#{tag}",
                "tag": [tag],
                "sort": "top",
                "since": (now - timedelta(days=max_age_days)).isoformat(),
                "limit": SOURCE_FEED_LIMIT,
            }
        ),
        deadline,
        f"searching repost candidates for #{tag}",
    )
    posts = get_nested_value(response, "posts")
    if not isinstance(posts, list):
        raise ValueError("Repost tag search has no posts list")
    return [as_dict(post) for post in posts]


def _humour_tags() -> set[str]:
    tags = {
        tag.casefold()
        for tag in config.get_follow_fellows_config()["hashtags"]
        if tag.casefold() != "followback"
    }
    if not tags:
        raise ValueError("Repost discovery requires follow-fellows humour tags")
    return tags


def _ranked_candidates(client, posts, counts, excluded, now, deadline, budget):
    tags = _humour_tags()
    max_age_days = config.get_repost_reviews_config()["max_post_age_days"]
    for tag in sorted(tags):
        posts.extend(_tag_posts(client, tag, now, max_age_days, deadline))
    pool = {}
    for post in posts:
        if (
            post.get("uri") in excluded
            or post.get("author", {}).get("did") == client.me.did
        ):
            continue
        candidate = _candidate(client, post, now, deadline, tags, max_age_days)
        if candidate is not None:
            rank = (
                counts[candidate["post"]["author_did"]],
                post.get("likeCount", 0) + post.get("repostCount", 0),
                timestamp(post["record"]["createdAt"]),
                candidate["key"],
            )
            pool[candidate["key"]] = (rank, candidate)
    selected = []
    authors = set()
    for _, candidate in sorted(pool.values(), key=lambda item: item[0], reverse=True):
        author = candidate["post"]["author_did"]
        if author not in authors:
            authors.add(author)
            selected.append(candidate)
            if len(selected) == budget:
                break
    return selected


def remaining_review_budget(state: dict, now=None, *, reserve_pending=True) -> int:
    cutoff = utc_now(now) - timedelta(days=REVIEW_WINDOW_DAYS)
    used = 0
    for candidate in state.get("repost_reviews", {}).get("candidates", {}).values():
        if candidate["action"] != "repost":
            continue
        if candidate.get("issue_id"):
            counted = timestamp(candidate["review_ready_at"]) > cutoff
        elif candidate.get("delivery_attempted"):
            # An unbound attempt may already have created an issue.
            counted = True
        else:
            counted = reserve_pending and timestamp(candidate["queued_at"]) > cutoff
        used += bool(counted)
    return max(0, MAX_CANDIDATES - used)


def discover(
    client, state: dict, now: datetime | None = None, *, preview: bool = False
) -> dict:
    deadline = time.monotonic() + MAX_RUNTIME_SECONDS
    inventory = read_inventory(client, now, deadline=deadline)
    now = utc_now(now)
    saved = state.get("repost_reviews", {})
    previous = saved.get("candidates", {})
    excluded = {entry["post_uri"] for entry in inventory["entries"]}
    excluded.update(entry["post"]["uri"] for entry in previous.values())
    counts = Counter(entry["author_did"] for entry in inventory["entries"])
    authors = sorted(
        (
            set(saved.get("source_dids", []))
            | {entry["author_did"] for entry in inventory["entries"]}
        )
        - {client.me.did},
        key=lambda did: (-counts[did], did),
    )
    budget = MAX_CANDIDATES if preview else remaining_review_budget(state, now)
    offset = saved.get("source_offset", 0)
    posts = []
    visited = 0
    while authors and visited < min(len(authors), MAX_SOURCE_ACCOUNTS) and budget > 0:
        author = authors[(offset + visited) % len(authors)]
        visited += 1
        posts.extend(_author_posts(client, author, deadline))
    candidates = (
        _ranked_candidates(client, posts, counts, excluded, now, deadline, budget)
        if budget
        else []
    )
    return {
        "inventory": inventory,
        "candidates": candidates,
        "source_dids": authors,
        "source_offset": (offset + visited) % len(authors) if authors else 0,
        "sampled_accounts": visited,
        "posts_per_source": SOURCE_FEED_LIMIT,
    }


def checkpoint_discovery(state: dict, report: dict) -> None:
    def record(latest):
        reviews = latest["repost_reviews"]
        reviews["inventory"] = copy.deepcopy(report["inventory"])
        reviews["source_dids"] = sorted(
            set(reviews["source_dids"]) | set(report["source_dids"])
        )
        reviews["source_offset"] = report["source_offset"]
        for candidate in report["candidates"]:
            reviews["candidates"].setdefault(candidate["key"], copy.deepcopy(candidate))
        content_creators.record_protections(latest, set(report["source_dids"]))

    state_transactions.apply(state, record)


def update_review(state: dict, key: str, **changes) -> dict:
    def record(latest):
        latest["repost_reviews"]["candidates"][key].update(copy.deepcopy(changes))
        if changes.get("status") == "published":
            author = latest["repost_reviews"]["candidates"][key]["post"]["author_did"]
            content_creators.record_protections(latest, {author})

    state_transactions.apply(state, record)
    return copy.deepcopy(state["repost_reviews"]["candidates"][key])


def require_live() -> None:
    if (
        os.getenv("BLUESKY_REPOSTS_ENABLED") != "true"
        or get_runtime_controls()["dry_run"]
    ):
        raise ValueError("Live repost actions are disabled")


def _receipt(client, candidate: dict) -> dict:
    uri = candidate["repost_uri"]
    prefix = f"at://{client.me.did}/{COLLECTION}/"
    if (
        not isinstance(uri, str)
        or not uri.startswith(prefix)
        or not re.fullmatch(r"[A-Za-z0-9._~:-]+", uri[len(prefix) :])
    ):
        raise ValueError("Repost receipt belongs to an unexpected repository")
    response = retry_network_call(
        lambda: client.com.atproto.repo.get_record(
            {
                "repo": client.me.did,
                "collection": COLLECTION,
                "rkey": uri[len(prefix) :],
            }
        ),
        description="verifying the reviewed repost record",
    )
    receipt = as_dict(response)
    value = as_dict(receipt.get("value"))
    if (
        receipt.get("uri") != uri
        or receipt.get("cid") != candidate.get("repost_cid")
        or value.get("$type") != COLLECTION
        or get_nested_value(value, "subject", "uri") != candidate["post"]["uri"]
        or get_nested_value(value, "subject", "cid") != candidate["post"]["cid"]
    ):
        raise ValueError("Repost receipt does not match the reviewed post")
    return receipt


def _current_post(client, candidate: dict, deadline: float) -> dict:
    expected = candidate["post"]
    posts = _posts(client, [expected["uri"]], deadline)
    post = posts.get(expected["uri"])
    if post is None or preview_post(post)["cid"] != expected["cid"]:
        raise ValueError("Reviewed post is missing or changed")
    if _context(client, post, deadline) != candidate["context"]:
        raise ValueError("Reviewed thread context changed")
    return post


def _confirm(client, state, candidate, now):
    _receipt(client, candidate)
    return update_review(
        state,
        candidate["key"],
        status="published",
        published_at=utc_now(now).isoformat(),
    )


def _create_repost(client, state, candidate, now):
    key = candidate["key"]

    def begin(latest):
        saved = latest["repost_reviews"]["candidates"][key]
        if saved["status"] != "approved":
            raise ValueError("Repost approval changed; refusing a stale publication")
        saved["status"] = "publishing"

    state_transactions.apply(state, begin)
    require_live()
    try:
        response = as_dict(
            client.repost(uri=candidate["post"]["uri"], cid=candidate["post"]["cid"])
        )
        if not isinstance(response.get("uri"), str) or not isinstance(
            response.get("cid"), str
        ):
            raise ValueError("Repost response has no record receipt")
        candidate = update_review(
            state, key, repost_uri=response["uri"], repost_cid=response["cid"]
        )
        return _confirm(client, state, candidate, now)
    except requests.RequestException, AtProtocolError, TimeoutError, ValueError:
        update_review(state, key, status="uncertain")
        raise


def publish(client, state: dict, key: str, now: datetime | None = None) -> dict:
    require_live()
    candidate = state["repost_reviews"]["candidates"][key]
    if candidate["action"] != "repost":
        raise ValueError("This review is not a repost approval")
    if candidate["status"] in ("published", "already_reposted"):
        return copy.deepcopy(candidate)
    if candidate["status"] not in ("approved", "publishing", "uncertain"):
        raise ValueError("Repost has not been approved")
    if candidate.get("repost_uri"):
        return _confirm(client, state, candidate, now)
    if timestamp(candidate["expires_at"]) <= utc_now(now):
        raise ValueError("Repost review has expired")
    post = _current_post(client, candidate, time.monotonic() + MAX_RUNTIME_SECONDS)
    if get_nested_value(post, "viewer", "repost"):
        return update_review(state, key, status="already_reposted")
    if candidate["status"] in ("uncertain", "publishing"):
        raise ValueError(
            "Previous repost outcome is uncertain; investigate before retrying"
        )
    if not _available(post):
        raise ValueError("Reviewed post is no longer eligible")
    if timestamp(candidate["expires_at"]) <= utc_now(now):
        raise ValueError("Repost review has expired")
    return _create_repost(client, state, candidate, now)


def _delete_repost(client, state, candidate, now):
    key = candidate["key"]

    def begin(latest):
        saved = latest["repost_reviews"]["candidates"][key]
        if saved["status"] != candidate["status"]:
            raise ValueError("Repost removal approval changed; refusing a stale action")
        saved["status"] = "removing"

    state_transactions.apply(state, begin)
    require_live()
    try:
        if not client.delete_repost(candidate["repost_uri"]):
            raise ValueError("Repost removal was not confirmed")
    except requests.RequestException, AtProtocolError, TimeoutError, ValueError:
        update_review(state, key, status="uncertain")
        raise
    return update_review(
        state, key, status="removed", removed_at=utc_now(now).isoformat()
    )


def remove(client, state: dict, key: str, now: datetime | None = None) -> dict:
    require_live()
    candidate = state["repost_reviews"]["candidates"][key]
    if candidate["status"] == "removed":
        return copy.deepcopy(candidate)
    if candidate["action"] != "remove" or candidate["status"] not in (
        "approved",
        "removing",
        "uncertain",
    ):
        raise ValueError("Repost removal has not been approved")
    try:
        _receipt(client, candidate)
    except BadRequestError as exc:
        if (
            get_nested_value(exc, "response", "status_code") != 400
            or get_nested_value(exc, "response", "content", "error") != "RecordNotFound"
        ):
            raise
        return update_review(state, key, status="already_removed")
    if timestamp(candidate["expires_at"]) <= utc_now(now):
        raise ValueError("Repost removal review has expired")
    return _delete_repost(client, state, candidate, now)
