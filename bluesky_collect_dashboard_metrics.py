"""Collect aggregate public Bluesky metrics for the static dashboard."""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

import bluesky_state
from bluesky_common import retry_network_call

PUBLIC_API_BASE = "https://public.api.bsky.app/xrpc"
METRICS_FILE = Path(__file__).resolve().parent / "dashboard" / "data" / "metrics.json"
SCHEMA_VERSION = 1
MAX_FEED_PAGES = 100
MAX_FEED_RUNTIME_SECONDS = 120
ENGAGEMENT_FIELDS = (
    ("likes", "likeCount"),
    ("replies", "replyCount"),
    ("reposts", "repostCount"),
    ("quotes", "quoteCount"),
    ("bookmarks", "bookmarkCount"),
)


def _request_json(session, method: str, params: dict) -> dict:
    def _request():
        response = session.get(f"{PUBLIC_API_BASE}/{method}", params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected {method} response format")
        return payload

    return retry_network_call(_request, description=f"fetching {method}")


def fetch_profile(session, actor: str) -> dict:
    profile = _request_json(session, "app.bsky.actor.getProfile", {"actor": actor})
    required = ("did", "handle", "followersCount", "followsCount", "postsCount")
    if any(field not in profile for field in required):
        raise ValueError("Bluesky profile response is missing required counters")
    return profile


def fetch_post(session, uri: str) -> dict:
    payload = _request_json(session, "app.bsky.feed.getPosts", {"uris": [uri]})
    posts = payload.get("posts")
    if not isinstance(posts, list) or len(posts) != 1:
        raise ValueError("Latest joke could not be hydrated from Bluesky")
    return posts[0]


def _original_post(item: object, actor_did: str) -> dict | None:
    if not isinstance(item, dict) or item.get("reason") is not None:
        return None
    post = item.get("post")
    if not isinstance(post, dict):
        return None
    record = post.get("record", {})
    author = post.get("author", {})
    if (
        isinstance(record, dict)
        and isinstance(author, dict)
        and author.get("did") == actor_did
        and not record.get("reply")
        and post.get("uri")
    ):
        return post
    return None


def _collect_original_posts(posts: dict[str, dict], feed: list, actor_did: str) -> None:
    for item in feed:
        post = _original_post(item, actor_did)
        if post:
            posts[post["uri"]] = post


def fetch_original_posts(
    session,
    actor_did: str,
    max_pages: int = MAX_FEED_PAGES,
    max_runtime_seconds: int = MAX_FEED_RUNTIME_SECONDS,
) -> list[dict]:
    posts: dict[str, dict] = {}
    cursor = None
    seen_cursors: set[str] = set()
    started_at = time.monotonic()

    for page_number in range(1, max_pages + 1):
        if time.monotonic() - started_at >= max_runtime_seconds:
            raise RuntimeError("Author-feed pagination exceeded its runtime limit")
        if cursor in seen_cursors:
            raise RuntimeError("Author-feed pagination returned a repeated cursor")
        if cursor:
            seen_cursors.add(cursor)

        params = {
            "actor": actor_did,
            "filter": "posts_no_replies",
            "includePins": "false",
            "limit": 100,
        }
        if cursor:
            params["cursor"] = cursor
        payload = _request_json(session, "app.bsky.feed.getAuthorFeed", params)
        feed = payload.get("feed")
        if not isinstance(feed, list):
            raise ValueError("Author-feed response is missing its feed list")

        _collect_original_posts(posts, feed, actor_did)

        next_cursor = payload.get("cursor")
        if not next_cursor:
            return list(posts.values())
        if next_cursor == cursor:
            raise RuntimeError("Author-feed pagination returned a repeated cursor")
        cursor = next_cursor

    raise RuntimeError(
        f"Author-feed pagination exceeded its {max_pages}-page safety limit"
    )


def _engagement(post: dict) -> dict[str, int]:
    return {
        name: max(0, int(post.get(api_name) or 0))
        for name, api_name in ENGAGEMENT_FIELDS
    }


def _post_summary(post: dict, handle: str) -> dict:
    uri = post["uri"]
    record = post.get("record", {})
    return {
        "uri": uri,
        "url": f"https://bsky.app/profile/{handle}/post/{uri.rsplit('/', 1)[-1]}",
        "text": str(record.get("text") or ""),
        "created_at": record.get("createdAt") or post.get("indexedAt"),
        "engagement": _engagement(post),
    }


def _latest_joke_uri(state: dict) -> str:
    deleted = set(state.get("reports", {}).get("deleted_post_uris", []))
    for entry in reversed(state.get("posted_jokes", [])):
        uri = entry.get("post_uri")
        if uri and uri not in deleted:
            return uri
    raise ValueError("No published joke URI is available for the dashboard")


def _daily_activity(state: dict) -> list[dict]:
    posts = Counter()
    unfollows = Counter()
    for entry in state.get("posted_jokes", []):
        if entry.get("ts"):
            posts[
                datetime.fromtimestamp(entry["ts"], timezone.utc).date().isoformat()
            ] += 1
    for entry in state.get("unfollow_history", {}).get("entries", []):
        if entry.get("unfollowed_at"):
            day = (
                datetime.fromtimestamp(entry["unfollowed_at"], timezone.utc)
                .date()
                .isoformat()
            )
            unfollows[day] += 1
    return [
        {"date": day, "joke_posts": posts[day], "unfollows": unfollows[day]}
        for day in sorted(posts.keys() | unfollows.keys())
    ]


def _period_start(now: datetime) -> str:
    bucket_hour = now.hour - (now.hour % 6)
    return now.replace(hour=bucket_hour, minute=0, second=0, microsecond=0).isoformat()


def _normalise_existing(existing: dict | None) -> dict:
    if existing is None:
        return {"schema_version": SCHEMA_VERSION, "snapshots": []}
    if existing.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported dashboard metrics schema version")
    if not isinstance(existing.get("snapshots"), list):
        raise ValueError("Dashboard metrics snapshots must be a list")
    return existing


def collect_metrics(
    actor: str,
    state: dict,
    existing: dict | None = None,
    session=None,
    now: datetime | None = None,
) -> dict:
    session = session or requests.Session()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Dashboard collection time must include a timezone")
    existing = _normalise_existing(existing)

    profile = fetch_profile(session, actor)
    latest_post = fetch_post(session, _latest_joke_uri(state))
    original_posts = fetch_original_posts(session, profile["did"])
    joke_uris = {
        entry.get("post_uri")
        for entry in state.get("posted_jokes", [])
        if entry.get("post_uri")
    }
    joke_posts = [post for post in original_posts if post.get("uri") in joke_uris]

    totals = {name: 0 for name, _ in ENGAGEMENT_FIELDS}
    for post in joke_posts:
        for name, count in _engagement(post).items():
            totals[name] += count
    engagement_total = sum(totals.values())
    current = {
        "followers": int(profile["followersCount"]),
        "following": int(profile["followsCount"]),
        "profile_posts": int(profile["postsCount"]),
        "joke_posts": len(joke_posts),
        "engagement": totals,
        "engagement_per_joke": round(engagement_total / len(joke_posts), 2)
        if joke_posts
        else 0.0,
    }
    snapshot = {
        "period_start": _period_start(now),
        "collected_at": now.isoformat(),
        "followers": current["followers"],
        "following": current["following"],
        "profile_posts": current["profile_posts"],
    }
    snapshots = [
        item
        for item in existing["snapshots"]
        if item.get("period_start") != snapshot["period_start"]
    ]
    snapshots.append(snapshot)
    snapshots.sort(key=lambda item: item["period_start"])

    ranked_posts = sorted(
        joke_posts,
        key=lambda post: sum(_engagement(post).values()),
        reverse=True,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "account": {
            "handle": profile["handle"],
            "display_name": profile.get("displayName") or profile["handle"],
            "avatar": profile.get("avatar"),
            "profile_url": f"https://bsky.app/profile/{profile['handle']}",
        },
        "latest_joke": _post_summary(latest_post, profile["handle"]),
        "current": current,
        "snapshots": snapshots,
        "daily_activity": _daily_activity(state),
        "top_posts": [
            _post_summary(post, profile["handle"]) for post in ranked_posts[:5]
        ],
    }


def _load_existing() -> dict | None:
    if not METRICS_FILE.exists():
        return None
    with METRICS_FILE.open(encoding="utf-8") as metrics_file:
        return json.load(metrics_file)


def _write_metrics(metrics: dict) -> None:
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = METRICS_FILE.with_suffix(".json.tmp")
    with temporary_path.open("w", encoding="utf-8") as metrics_file:
        json.dump(metrics, metrics_file, indent=2)
        metrics_file.write("\n")
    os.replace(temporary_path, METRICS_FILE)


def main() -> None:
    actor = os.getenv("BLUESKY_USERNAME", "").strip()
    if not actor:
        raise ValueError("BLUESKY_USERNAME is required to collect dashboard metrics")
    metrics = collect_metrics(actor, bluesky_state.load_state(), _load_existing())
    _write_metrics(metrics)
    print(
        f"Dashboard metrics updated for @{metrics['account']['handle']} "
        f"at {metrics['generated_at']}."
    )


if __name__ == "__main__":
    main()
