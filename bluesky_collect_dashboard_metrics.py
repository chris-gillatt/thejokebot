"""Collect aggregate public Bluesky metrics for the static dashboard."""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import bluesky_state
from bluesky_common import retry_network_call

PUBLIC_API_BASE = "https://public.api.bsky.app/xrpc"
GITHUB_API_BASE = "https://api.github.com"
METRICS_FILE = Path(__file__).resolve().parent / "dashboard" / "data" / "metrics.json"
SCHEMA_VERSION = 2
MAX_FEED_PAGES = 100
MAX_FEED_RUNTIME_SECONDS = 120
MAX_WORKFLOW_PAGES = 20
WORKFLOW_WINDOW_DAYS = 30
TRACKED_WORKFLOWS = {
    "bluesky_dashboard",
    "bluesky_follow_fellows",
    "bluesky_follows_and_likes",
    "bluesky_manage_starter_pack",
    "bluesky_post_joke",
    "bluesky_process_reports",
    "bluesky_unfollow",
    "bluesky_validate_unfollow_ignore",
    "codeql",
    "pr_auto_merge",
    "provider_health_check",
    "python_tests",
    "ruff_quality",
    "validate_runtime_config",
}
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


def fetch_workflow_runs(
    session,
    repository: str,
    token: str | None,
    now: datetime,
    max_pages: int = MAX_WORKFLOW_PAGES,
) -> list[dict]:
    cutoff = now - timedelta(days=WORKFLOW_WINDOW_DAYS)
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    runs = []
    for page_number in range(1, max_pages + 1):

        def _request():
            response = session.get(
                f"{GITHUB_API_BASE}/repos/{repository}/actions/runs",
                params={
                    "created": f">={cutoff.isoformat()}",
                    "per_page": 100,
                    "page": page_number,
                },
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()

        payload = retry_network_call(
            _request, description=f"fetching GitHub Actions page {page_number}"
        )
        page_runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
        if not isinstance(page_runs, list):
            raise ValueError("GitHub Actions response is missing workflow_runs")
        runs.extend(page_runs)
        if len(page_runs) < 100:
            return runs

    raise RuntimeError(
        f"GitHub Actions pagination exceeded its {max_pages}-page safety limit"
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
    if existing.get("schema_version") not in {1, SCHEMA_VERSION}:
        raise ValueError("Unsupported dashboard metrics schema version")
    if not isinstance(existing.get("snapshots"), list):
        raise ValueError("Dashboard metrics snapshots must be a list")
    existing["schema_version"] = SCHEMA_VERSION
    return existing


def _provider_metrics(state: dict, joke_posts: list[dict]) -> dict:
    retained_publications = Counter(
        entry.get("provider") or "unknown" for entry in state.get("posted_jokes", [])
    )
    provider_by_uri = {
        entry.get("post_uri"): entry.get("provider") or "unknown"
        for entry in state.get("posted_jokes", [])
        if entry.get("post_uri")
    }
    visible = {}
    for post in joke_posts:
        provider_name = provider_by_uri.get(post.get("uri"), "unknown")
        summary = visible.setdefault(
            provider_name, {"visible_posts": 0, "interactions": 0}
        )
        summary["visible_posts"] += 1
        summary["interactions"] += sum(_engagement(post).values())

    failures = state.get("provider", {}).get("failures", {})
    health_checks = state.get("provider", {}).get("health_checks", {})
    provider_names = sorted(
        retained_publications.keys() | failures.keys() | health_checks.keys()
    )
    providers = []
    for provider_name in provider_names:
        visible_summary = visible.get(
            provider_name, {"visible_posts": 0, "interactions": 0}
        )
        visible_posts = visible_summary["visible_posts"]
        failure = failures.get(provider_name, {})
        health = health_checks.get(provider_name, {})
        providers.append(
            {
                "name": provider_name,
                "published": retained_publications[provider_name],
                "visible_posts": visible_posts,
                "average_interactions": round(
                    visible_summary["interactions"] / visible_posts, 2
                )
                if visible_posts
                else None,
                "fallthroughs": int(failure.get("count") or 0),
                "last_failure_at": failure.get("last_failure_at"),
                "last_failure_reason": failure.get("last_error"),
                "healthy": health.get("last_check_success"),
                "configured": health.get("configured"),
                "last_health_check_at": health.get("last_check_at"),
                "consecutive_health_failures": int(
                    health.get("consecutive_failures") or 0
                ),
            }
        )
    providers.sort(key=lambda item: (-item["published"], item["name"]))
    return {
        "retained_publications": sum(retained_publications.values()),
        "providers": providers,
    }


def _workflow_metrics(workflow_runs: list[dict], now: datetime) -> dict:
    grouped = {
        name: {
            "name": name,
            "runs": 0,
            "successful": 0,
            "failed": 0,
            "cancelled": 0,
            "last_run_at": None,
            "last_conclusion": None,
        }
        for name in TRACKED_WORKFLOWS
    }
    for run in workflow_runs:
        name = str(run.get("name") or "unknown")
        if name not in TRACKED_WORKFLOWS:
            continue
        summary = grouped[name]
        summary["runs"] += 1
        conclusion = run.get("conclusion")
        if conclusion == "success":
            summary["successful"] += 1
        elif conclusion == "failure":
            summary["failed"] += 1
        elif conclusion == "cancelled":
            summary["cancelled"] += 1
        created_at = run.get("created_at")
        if created_at and (
            summary["last_run_at"] is None or created_at > summary["last_run_at"]
        ):
            summary["last_run_at"] = created_at
            summary["last_conclusion"] = conclusion

    workflows = sorted(grouped.values(), key=lambda item: item["name"])
    completed = sum(item["successful"] + item["failed"] for item in workflows)
    successful = sum(item["successful"] for item in workflows)
    return {
        "window_days": WORKFLOW_WINDOW_DAYS,
        "collected_at": now.isoformat(),
        "runs": sum(item["runs"] for item in workflows),
        "successful": successful,
        "failed": sum(item["failed"] for item in workflows),
        "cancelled": sum(item["cancelled"] for item in workflows),
        "success_rate": round(successful * 100 / completed, 1) if completed else None,
        "workflows": workflows,
    }


def collect_metrics(
    actor: str,
    state: dict,
    existing: dict | None = None,
    session=None,
    now: datetime | None = None,
    workflow_runs: list[dict] | None = None,
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
        "providers": _provider_metrics(state, joke_posts),
        "automation": _workflow_metrics(workflow_runs or [], now),
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
    now = datetime.now(timezone.utc)
    session = requests.Session()
    repository = os.getenv("GITHUB_REPOSITORY", "chris-gillatt/thejokebot").strip()
    workflow_runs = fetch_workflow_runs(
        session,
        repository,
        os.getenv("GITHUB_TOKEN"),
        now,
    )
    metrics = collect_metrics(
        actor,
        bluesky_state.load_state(),
        _load_existing(),
        session=session,
        now=now,
        workflow_runs=workflow_runs,
    )
    _write_metrics(metrics)
    print(
        f"Dashboard metrics updated for @{metrics['account']['handle']} "
        f"at {metrics['generated_at']}."
    )


if __name__ == "__main__":
    main()
