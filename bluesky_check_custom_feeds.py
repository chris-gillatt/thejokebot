"""Read-only helper to audit custom-feed visibility for recent bot posts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
from typing import Any

from bluesky_common import login_client

_CONFIG_PATH = pathlib.Path(__file__).parent / "resources" / "jokebot_custom_feeds.json"
_DEFAULT_DAYS = 14
_DEFAULT_AUTHOR_PAGE_LIMIT = 5
_DEFAULT_FEED_PAGE_LIMIT = 3
_PAGE_SIZE = 100


def load_config() -> dict[str, Any]:
    if not _CONFIG_PATH.exists():
        return {"custom_feeds": {"enabled": False, "target_feeds": []}}
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        print(f"Failed to read custom feed config: {exc}")
        return {"custom_feeds": {"enabled": False, "target_feeds": []}}
    if not isinstance(data, dict):
        return {"custom_feeds": {"enabled": False, "target_feeds": []}}
    return data


def _normalise_feed_uri(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    uri = value.strip()
    if not uri.startswith("at://"):
        return None
    return uri


def _looks_like_placeholder(uri: str) -> bool:
    return "did:example" in uri or uri.endswith("/example")


def _extract_post_uri(item) -> str | None:
    post = getattr(item, "post", None)
    if post is None and isinstance(item, dict):
        post = item.get("post")
    if post is None:
        return None
    if isinstance(post, dict):
        return post.get("uri")
    return getattr(post, "uri", None)


def _extract_post_created_at(item) -> str | None:
    post = getattr(item, "post", None)
    if post is None and isinstance(item, dict):
        post = item.get("post")
    if post is None:
        return None

    record = getattr(post, "record", None)
    if record is None and isinstance(post, dict):
        record = post.get("record")
    if isinstance(record, dict):
        created = record.get("createdAt")
        if isinstance(created, str):
            return created
    elif record is not None:
        created = getattr(record, "created_at", None) or getattr(record, "createdAt", None)
        if isinstance(created, str):
            return created

    indexed = getattr(post, "indexed_at", None) or getattr(post, "indexedAt", None)
    if not indexed and isinstance(post, dict):
        indexed = post.get("indexedAt") or post.get("indexed_at")
    return indexed if isinstance(indexed, str) else None


def _extract_post_author_did(item) -> str | None:
    post = getattr(item, "post", None)
    if post is None and isinstance(item, dict):
        post = item.get("post")
    if post is None:
        return None

    author = getattr(post, "author", None)
    if author is None and isinstance(post, dict):
        author = post.get("author")
    if isinstance(author, dict):
        did = author.get("did")
        return did if isinstance(did, str) else None
    if author is None:
        return None
    did = getattr(author, "did", None)
    return did if isinstance(did, str) else None


def _parse_iso(ts: str | None) -> dt.datetime | None:
    if not ts:
        return None
    raw = ts.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def get_recent_author_post_uris(client, actor: str, author_did: str | None, since_dt: dt.datetime) -> set[str]:
    uris: set[str] = set()
    cursor = None

    for _ in range(_DEFAULT_AUTHOR_PAGE_LIMIT):
        params: dict[str, Any] = {"actor": actor, "limit": _PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor

        response = client.get_author_feed(**params)
        items = getattr(response, "feed", []) or []
        if not items:
            break

        hit_older_than_window = False
        for item in items:
            created_at = _parse_iso(_extract_post_created_at(item))
            if created_at is None:
                continue
            if created_at < since_dt:
                hit_older_than_window = True
                continue

            item_author_did = _extract_post_author_did(item)
            if author_did and item_author_did and item_author_did != author_did:
                continue

            uri = _extract_post_uri(item)
            if uri:
                uris.add(uri)

        cursor = getattr(response, "cursor", None)
        if not cursor or hit_older_than_window:
            break

    return uris


def get_feed_uris(client, feed_uri: str) -> set[str]:
    uris: set[str] = set()
    cursor = None

    for _ in range(_DEFAULT_FEED_PAGE_LIMIT):
        params = {"feed": feed_uri, "limit": _PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor

        response = client.app.bsky.feed.get_feed(params=params)
        items = getattr(response, "feed", []) or []
        for item in items:
            uri = _extract_post_uri(item)
            if uri:
                uris.add(uri)

        cursor = getattr(response, "cursor", None)
        if not cursor:
            break

    return uris


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit custom-feed visibility for recent posts")
    parser.add_argument("--days", type=int, default=_DEFAULT_DAYS, help="Days of authored posts to audit")
    parser.add_argument(
        "--out-json",
        type=str,
        default="",
        help="Optional output path for machine-readable JSON summary",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.days <= 0:
        print("--days must be greater than 0")
        return 2

    since_dt = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)
    config = load_config().get("custom_feeds", {})
    target_feeds = config.get("target_feeds") if isinstance(config, dict) else []
    if not isinstance(target_feeds, list):
        target_feeds = []

    client, username = login_client()
    actor = getattr(client.me, "did", None) or username
    author_did = getattr(client.me, "did", None)

    selected_feeds = []
    for feed_cfg in target_feeds:
        if not isinstance(feed_cfg, dict):
            continue
        feed_uri = _normalise_feed_uri(feed_cfg.get("uri"))
        if not feed_uri or _looks_like_placeholder(feed_uri):
            continue
        selected_feeds.append({
            "name": str(feed_cfg.get("name") or "Configured feed"),
            "uri": feed_uri,
        })

    if not selected_feeds:
        print(
            "No valid custom feeds configured in resources/jokebot_custom_feeds.json. "
            "Add at least one real feed URI to custom_feeds.target_feeds."
        )
        return 0

    recent_uris = get_recent_author_post_uris(client, actor, author_did, since_dt)

    if not recent_uris:
        print(f"No authored post URIs found in the last {args.days} day(s).")
        return 0

    print(
        f"Checking {len(selected_feeds)} feed(s) against {len(recent_uris)} "
        f"authored posts from the last {args.days} day(s) (configured)..."
    )
    total_matches = 0
    per_feed_results = []

    unique_matched_uris: set[str] = set()

    for feed_cfg in selected_feeds:
        name = str(feed_cfg.get("name") or "Unnamed feed")
        feed_uri = str(feed_cfg.get("uri") or "").strip()
        if not feed_uri:
            print(f"- {name}: skipped (missing URI)")
            per_feed_results.append({
                "name": name,
                "uri": feed_uri,
                "status": "invalid",
                "matches": 0,
                "coverage_pct": 0.0,
                "error": "missing URI",
            })
            continue

        try:
            feed_uris = get_feed_uris(client, feed_uri)
        except Exception as exc:  # defensive read-only helper; do not fail whole run
            print(f"- {name}: error fetching feed: {exc}")
            per_feed_results.append({
                "name": name,
                "uri": feed_uri,
                "status": "error",
                "matches": 0,
                "coverage_pct": 0.0,
                "error": str(exc),
            })
            continue

        matches = sorted(recent_uris.intersection(feed_uris))
        total_matches += len(matches)
        unique_matched_uris |= set(matches)
        coverage_pct = round((len(matches) / len(recent_uris)) * 100, 2) if recent_uris else 0.0

        print(f"- {name}: {len(matches)} match(es) ({coverage_pct}%)")
        if matches:
            print(f"  latest match: {matches[-1]}")

        per_feed_results.append({
            "name": name,
            "uri": feed_uri,
            "status": "ok",
            "matches": len(matches),
            "coverage_pct": coverage_pct,
            "error": None,
        })

    unique_match_pct = round((len(unique_matched_uris) / len(recent_uris)) * 100, 2) if recent_uris else 0.0
    print(
        f"Done. Total feed matches: {total_matches}. "
        f"Unique posts seen in at least one feed: {len(unique_matched_uris)}/{len(recent_uris)} "
        f"({unique_match_pct}%)."
    )

    if args.out_json:
        payload = {
            "window_days": args.days,
            "window_start_utc": since_dt.isoformat(),
            "feed_source": "configured",
            "recent_post_count": len(recent_uris),
            "total_matches": total_matches,
            "unique_posts_in_any_feed": len(unique_matched_uris),
            "unique_posts_in_any_feed_pct": unique_match_pct,
            "feeds": per_feed_results,
        }
        out_path = pathlib.Path(args.out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        print(f"Wrote JSON summary to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
