"""Collect aggregate public Bluesky metrics for the static dashboard."""

from __future__ import annotations

import io
import json
import os
import re
import time
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

import requests

import bluesky_config
import bluesky_state
from bluesky_common import retry_network_call

PUBLIC_API_BASE = "https://public.api.bsky.app/xrpc"
GITHUB_API_BASE = "https://api.github.com"
METRICS_FILE = Path(__file__).resolve().parent / "dashboard" / "data" / "metrics.json"
SCHEMA_VERSION = 7
MAX_FEED_PAGES = 100
MAX_FEED_RUNTIME_SECONDS = 120
MAX_WORKFLOW_PAGES = 20
MAX_WORKFLOW_LOG_BYTES = 25 * 1024 * 1024
MAX_WORKFLOW_LOG_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
WORKFLOW_WINDOW_DAYS = 30
TOP_POST_LIMIT = 6
POSTING_DELIVERY_WINDOWS = (7, 30)
POSTING_SLOT_MATCH_HOURS = 2
CORE_WORKFLOWS = {
    "bluesky_dashboard",
    "bluesky_follows_and_likes",
    "bluesky_post_joke",
    "bluesky_process_reports",
}
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
ACTIVITY_WORKFLOWS = {
    "bluesky_follow_fellows",
    "bluesky_follows_and_likes",
    "bluesky_manage_starter_pack",
    "bluesky_post_joke",
    "bluesky_process_reports",
    "bluesky_unfollow",
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


def _github_headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_workflow_runs(
    session,
    repository: str,
    token: str | None,
    now: datetime,
    max_pages: int = MAX_WORKFLOW_PAGES,
) -> list[dict]:
    cutoff = now - timedelta(days=WORKFLOW_WINDOW_DAYS)
    headers = _github_headers(token)

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


def fetch_workflow_run_logs(
    session, repository: str, run_id: int, token: str | None
) -> str:
    def _request():
        response = session.get(
            f"{GITHUB_API_BASE}/repos/{repository}/actions/runs/{run_id}/logs",
            headers=_github_headers(token),
            timeout=30,
        )
        response.raise_for_status()
        return response.content

    archive_bytes = retry_network_call(
        _request, description=f"fetching GitHub Actions logs for run {run_id}"
    )
    if len(archive_bytes) > MAX_WORKFLOW_LOG_BYTES:
        raise ValueError(f"Workflow log archive for run {run_id} is too large")

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        files = [item for item in archive.infolist() if not item.is_dir()]
        if sum(item.file_size for item in files) > MAX_WORKFLOW_LOG_UNCOMPRESSED_BYTES:
            raise ValueError(f"Workflow logs for run {run_id} are too large")
        return "\n".join(
            archive.read(item).decode("utf-8", errors="replace") for item in files
        )


def _moderation_activity_counts(log_text: str) -> dict | None:
    summaries = re.findall(
        r"Moderation summary: proposals=(\d+), acknowledgements=(\d+), "
        r"approved_removals=(\d+), unresolved=(\d+)\.",
        log_text,
    )
    if not summaries:
        return None
    proposals, acknowledgements, approved_removals, unresolved = (
        int(value) for value in summaries[-1]
    )
    return {
        "follows": 0,
        "unfollows": 0,
        "proposals": proposals,
        "acknowledgements": acknowledgements,
        "approved_removals": approved_removals,
        "unresolved": unresolved,
    }


def _unfollow_activity_counts(log_text: str) -> dict | None:
    summaries = re.findall(
        r"\bSummary: processed=(\d+), unfollowed=(\d+), failed=(\d+), "
        r"missing_uri=(\d+)\.",
        log_text,
    )
    if not summaries:
        return None
    processed, unfollowed, failed, missing_uri = (int(value) for value in summaries[-1])
    eligible_values = re.findall(r"Found (\d+) users to unfollow", log_text)
    eligible = int(eligible_values[-1]) if eligible_values else processed
    return {
        "follows": 0,
        "unfollows": unfollowed,
        "eligible": eligible,
        "processed": processed,
        "failed": failed,
        "missing_uri": missing_uri,
        "stopped_early": "Run stopped early after throttle detection" in log_text,
    }


def _provider_activity_counts(log_text: str) -> dict | None:
    summaries = re.findall(
        r"Provider summary: attempts=(\d+), successful_source=([a-z0-9_-]+), "
        r"fallthrough=(true|false), static_fallback=(true|false), "
        r"duplicate=(\d+), too_long=(\d+), network_error=(\d+), "
        r"provider_error=(\d+), posted=(true|false)\.",
        log_text,
    )
    if not summaries:
        return None
    (
        attempts,
        successful_source,
        fallthrough,
        static_fallback,
        duplicate,
        too_long,
        network_error,
        provider_error,
        posted,
    ) = summaries[-1]
    return {
        "follows": 0,
        "unfollows": 0,
        "provider_attempts": int(attempts),
        "successful_source": successful_source,
        "fallthrough": fallthrough == "true",
        "static_fallback": static_fallback == "true",
        "duplicate": int(duplicate),
        "too_long": int(too_long),
        "network_error": int(network_error),
        "provider_error": int(provider_error),
        "posted": posted == "true",
    }


def _workflow_activity_counts(workflow_name: str, log_text: str) -> dict | None:
    plain_text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", log_text)
    if "Dry-run mode enabled" in plain_text:
        return {"follows": 0, "unfollows": 0}
    specialised_parser = {
        "bluesky_post_joke": _provider_activity_counts,
        "bluesky_process_reports": _moderation_activity_counts,
        "bluesky_unfollow": _unfollow_activity_counts,
    }.get(workflow_name)
    if specialised_parser:
        return specialised_parser(plain_text)
    if workflow_name == "bluesky_follows_and_likes":
        summaries = re.findall(
            r"Social summary: follow_back_candidates=(\d+), "
            r"follow_back_added=(\d+), protected=(\d+), "
            r"interaction_candidates=(\d+), interaction_eligible=(\d+), "
            r"interaction_added=(\d+), interactions_liked=(\d+), "
            r"failed=(\d+), dry_run=false\.",
            plain_text,
        )
        if summaries:
            (
                follow_back_candidates,
                follow_back_added,
                protected,
                interaction_candidates,
                interaction_eligible,
                interaction_added,
                interactions_liked,
                failed,
            ) = (int(value) for value in summaries[-1])
            return {
                "follows": follow_back_added + interaction_added,
                "unfollows": 0,
                "follow_back_candidates": follow_back_candidates,
                "follow_back_added": follow_back_added,
                "protected": protected,
                "interaction_candidates": interaction_candidates,
                "interaction_eligible": interaction_eligible,
                "interaction_added": interaction_added,
                "interactions_liked": interactions_liked,
                "failed": failed,
            }
        follows = len(re.findall(r"\bFollowed (?:interactor )?did:[^\s]+", plain_text))
        return {"follows": follows, "unfollows": 0}
    if workflow_name == "bluesky_follow_fellows":
        summaries = re.findall(
            r"Discovery summary: selected=(\d+), followed=(\d+), "
            r"failed=(\d+), dry_run=false\.",
            plain_text,
        )
        if summaries:
            selected, followed, failed = (int(value) for value in summaries[-1])
            return {
                "follows": followed,
                "unfollows": 0,
                "selected": selected,
                "failed": failed,
            }
        planned = re.findall(r"Total users to follow: (\d+)", plain_text)
        if not planned:
            return None
        failures = len(
            re.findall(r"Unexpected error trying to follow did:[^\s]+", plain_text)
        )
        selected = int(planned[-1])
        return {
            "follows": max(0, selected - failures),
            "unfollows": 0,
            "selected": selected,
            "failed": failures,
        }
    if workflow_name == "bluesky_manage_starter_pack":
        follows = len(re.findall(r"\bFollowed list member did:[^\s]+", plain_text))
        return {"follows": follows, "unfollows": 0}
    return None


def collect_workflow_activity(
    session,
    repository: str,
    token: str | None,
    workflow_runs: list[dict],
    existing: dict | None,
    now: datetime,
) -> dict:
    cutoff = now - timedelta(days=WORKFLOW_WINDOW_DAYS)
    previous_activity = (existing or {}).get("workflow_activity", {})
    previous_expired_value = previous_activity.get("expired_before")
    expired_before = (
        datetime.fromisoformat(previous_expired_value.replace("Z", "+00:00"))
        if previous_expired_value
        else None
    )
    cached_runs = {
        int(item["id"]): item
        for item in previous_activity.get("runs", [])
        if item.get("id") is not None
        and item.get("created_at")
        and datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")) >= cutoff
    }
    unavailable_at = []

    for run in workflow_runs:
        workflow_name = str(run.get("name") or "")
        created_at = run.get("created_at")
        run_id = run.get("id")
        attempt = int(run.get("run_attempt") or 1)
        if (
            workflow_name not in ACTIVITY_WORKFLOWS
            or run.get("conclusion") != "success"
            or not created_at
            or run_id is None
        ):
            continue
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if created < cutoff or (expired_before and created <= expired_before):
            continue
        cached = cached_runs.get(int(run_id))
        cached_attempt_matches = cached and int(cached.get("attempt") or 1) == attempt
        incomplete_discovery = workflow_name == "bluesky_follow_fellows" and (
            not cached
            or cached.get("workflow") != workflow_name
            or "selected" not in cached
            or "failed" not in cached
        )
        incomplete_unfollow = workflow_name == "bluesky_unfollow" and (
            not cached
            or cached.get("workflow") != workflow_name
            or "processed" not in cached
        )
        incomplete_moderation = workflow_name == "bluesky_process_reports" and (
            not cached
            or cached.get("workflow") != workflow_name
            or "proposals" not in cached
        )
        incomplete_provider = workflow_name == "bluesky_post_joke" and (
            not cached
            or cached.get("workflow") != workflow_name
            or "provider_attempts" not in cached
        )
        if (
            cached_attempt_matches
            and not incomplete_discovery
            and not incomplete_unfollow
            and not incomplete_moderation
            and not incomplete_provider
        ):
            continue
        try:
            counts = _workflow_activity_counts(
                workflow_name,
                fetch_workflow_run_logs(session, repository, int(run_id), token),
            )
        except (
            OSError,
            ValueError,
            zipfile.BadZipFile,
            requests.RequestException,
        ) as exc:
            print(
                f"Warning: could not collect activity from workflow run {run_id}: {exc}"
            )
            unavailable_at.append(created)
            if (
                isinstance(exc, requests.HTTPError)
                and exc.response is not None
                and exc.response.status_code == 410
                and (expired_before is None or created > expired_before)
            ):
                expired_before = created
            continue
        if counts is None:
            print(f"Warning: workflow run {run_id} has no recognised activity summary")
            unavailable_at.append(created)
            continue
        cached_runs[int(run_id)] = {
            "id": int(run_id),
            "attempt": attempt,
            "workflow": workflow_name,
            "created_at": created_at,
            **counts,
        }

    coverage_start = max(
        [cutoff, *unavailable_at, *([expired_before] if expired_before else [])]
    )
    return {
        "window_days": WORKFLOW_WINDOW_DAYS,
        "coverage_start": coverage_start.isoformat(),
        "expired_before": expired_before.isoformat() if expired_before else None,
        "runs": sorted(cached_runs.values(), key=lambda item: item["created_at"]),
    }


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


def _top_post_summaries(joke_posts: list[dict], handle: str) -> list[dict]:
    ranked_posts = sorted(
        joke_posts,
        key=lambda post: sum(_engagement(post).values()),
        reverse=True,
    )
    return [_post_summary(post, handle) for post in ranked_posts[:TOP_POST_LIMIT]]


def _top_posts_by_window(
    joke_posts: list[dict], handle: str, now: datetime
) -> dict[str, list[dict]]:
    windows = {"all": _top_post_summaries(joke_posts, handle)}
    for days in (7, 30):
        cutoff = now - timedelta(days=days)
        posts = []
        for post in joke_posts:
            record = post.get("record", {})
            created_at = record.get("createdAt") or post.get("indexedAt")
            if not created_at:
                continue
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if created >= cutoff:
                posts.append(post)
        windows[str(days)] = _top_post_summaries(posts, handle)
    return windows


def _latest_joke_uri(state: dict) -> str:
    deleted = set(state.get("reports", {}).get("deleted_post_uris", []))
    for entry in reversed(state.get("posted_jokes", [])):
        uri = entry.get("post_uri")
        if uri and uri not in deleted:
            return uri
    raise ValueError("No published joke URI is available for the dashboard")


def _activity_by_day(
    state: dict, workflow_activity: dict | None
) -> tuple[Counter, Counter, Counter]:
    posts = Counter()
    follows = Counter()
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
    for run in (workflow_activity or {}).get("runs", []):
        created_at = run.get("created_at")
        if not created_at:
            continue
        day = (
            datetime.fromisoformat(created_at.replace("Z", "+00:00")).date().isoformat()
        )
        follows[day] += max(0, int(run.get("follows") or 0))
        unfollows[day] = max(unfollows[day], max(0, int(run.get("unfollows") or 0)))
    return posts, follows, unfollows


def _daily_activity(state: dict, workflow_activity: dict | None = None) -> list[dict]:
    posts, follows, unfollows = _activity_by_day(state, workflow_activity)
    return [
        {
            "date": day,
            "joke_posts": posts[day],
            "follows": follows[day],
            "unfollows": unfollows[day],
        }
        for day in sorted(posts.keys() | follows.keys() | unfollows.keys())
    ]


def _discovery_metrics(workflow_activity: dict | None) -> dict:
    runs = []
    for run in (workflow_activity or {}).get("runs", []):
        if run.get("workflow") != "bluesky_follow_fellows":
            continue
        selected = max(0, int(run.get("selected") or 0))
        followed = max(0, int(run.get("follows") or 0))
        failed = max(0, int(run.get("failed") or 0))
        runs.append(
            {
                "created_at": run.get("created_at"),
                "selected": selected,
                "followed": followed,
                "failed": failed,
            }
        )

    selected_total = sum(run["selected"] for run in runs)
    followed_counts = [run["followed"] for run in runs]
    followed_total = sum(followed_counts)
    return {
        "window_days": int(
            (workflow_activity or {}).get("window_days") or WORKFLOW_WINDOW_DAYS
        ),
        "coverage_start": min(
            (run["created_at"] for run in runs if run["created_at"]), default=None
        ),
        "completed_runs": len(runs),
        "selected": selected_total,
        "followed": followed_total,
        "failed": sum(run["failed"] for run in runs),
        "completion_rate": round(followed_total * 100 / selected_total, 1)
        if selected_total
        else None,
        "average_per_run": round(followed_total / len(runs), 1) if runs else None,
        "median_per_run": round(float(median(followed_counts)), 1) if runs else None,
        "zero_result_runs": sum(count == 0 for count in followed_counts),
        "runs": runs,
    }


def _social_activity_metrics(workflow_activity: dict | None) -> dict:
    runs = []
    for run in (workflow_activity or {}).get("runs", []):
        if (
            run.get("workflow") != "bluesky_follows_and_likes"
            or "follow_back_candidates" not in run
        ):
            continue
        runs.append(
            {
                "created_at": run.get("created_at"),
                "follow_back_candidates": max(
                    0, int(run.get("follow_back_candidates") or 0)
                ),
                "follow_back_added": max(0, int(run.get("follow_back_added") or 0)),
                "protected": max(0, int(run.get("protected") or 0)),
                "interaction_candidates": max(
                    0, int(run.get("interaction_candidates") or 0)
                ),
                "interaction_eligible": max(
                    0, int(run.get("interaction_eligible") or 0)
                ),
                "interaction_added": max(0, int(run.get("interaction_added") or 0)),
                "interactions_liked": max(0, int(run.get("interactions_liked") or 0)),
                "failed": max(0, int(run.get("failed") or 0)),
            }
        )
    fields = (
        "follow_back_candidates",
        "follow_back_added",
        "protected",
        "interaction_candidates",
        "interaction_eligible",
        "interaction_added",
        "interactions_liked",
        "failed",
    )
    return {
        "window_days": WORKFLOW_WINDOW_DAYS,
        "completed_runs": len(runs),
        **{field: sum(run[field] for run in runs) for field in fields},
        "runs": runs,
    }


def _moderation_metrics(workflow_activity: dict | None) -> dict:
    runs = []
    for run in (workflow_activity or {}).get("runs", []):
        if run.get("workflow") != "bluesky_process_reports" or "proposals" not in run:
            continue
        runs.append(
            {
                "created_at": run.get("created_at"),
                "proposals": max(0, int(run.get("proposals") or 0)),
                "acknowledgements": max(0, int(run.get("acknowledgements") or 0)),
                "approved_removals": max(0, int(run.get("approved_removals") or 0)),
                "unresolved": max(0, int(run.get("unresolved") or 0)),
            }
        )
    latest_unresolved = runs[-1]["unresolved"] if runs else None
    return {
        "window_days": WORKFLOW_WINDOW_DAYS,
        "completed_runs": len(runs),
        "proposals": sum(run["proposals"] for run in runs),
        "acknowledgements": sum(run["acknowledgements"] for run in runs),
        "approved_removals": sum(run["approved_removals"] for run in runs),
        "unresolved": latest_unresolved,
        "runs": runs,
    }


def _provider_pressure_metrics(workflow_activity: dict | None, now: datetime) -> dict:
    observed_runs = []
    for run in (workflow_activity or {}).get("runs", []):
        if (
            run.get("workflow") != "bluesky_post_joke"
            or "provider_attempts" not in run
            or not run.get("created_at")
        ):
            continue
        observed_runs.append(
            {
                "created_at": run["created_at"],
                "provider_attempts": max(0, int(run.get("provider_attempts") or 0)),
                "successful_source": str(run.get("successful_source") or "unknown"),
                "fallthrough": bool(run.get("fallthrough")),
                "static_fallback": bool(run.get("static_fallback")),
                "posted": bool(run.get("posted")),
                "rejections": {
                    reason: max(0, int(run.get(reason) or 0))
                    for reason in (
                        "duplicate",
                        "too_long",
                        "network_error",
                        "provider_error",
                    )
                },
            }
        )

    windows = {}
    for days in (7, 30):
        cutoff = now - timedelta(days=days)
        runs = [
            run
            for run in observed_runs
            if datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
            >= cutoff
        ]
        fallthroughs = sum(run["fallthrough"] for run in runs)
        attempts = sum(run["provider_attempts"] for run in runs)
        sources = Counter(run["successful_source"] for run in runs)
        windows[str(days)] = {
            "completed_runs": len(runs),
            "posted_runs": sum(run["posted"] for run in runs),
            "provider_attempts": attempts,
            "average_attempts": round(attempts / len(runs), 1) if runs else None,
            "fallthroughs": fallthroughs,
            "fallthrough_rate": round(fallthroughs * 100 / len(runs), 1)
            if runs
            else None,
            "static_fallbacks": sum(run["static_fallback"] for run in runs),
            "rejections": {
                reason: sum(run["rejections"][reason] for run in runs)
                for reason in (
                    "duplicate",
                    "too_long",
                    "network_error",
                    "provider_error",
                )
            },
            "successful_sources": dict(sorted(sources.items())),
        }
    return {"windows": windows, "runs": observed_runs}


def _network_maintenance_metrics(
    state: dict, workflow_activity: dict | None, now: datetime
) -> dict:
    source_names = {
        "follow_fellows": "discovery",
        "interaction": "interaction",
        "manual_reconciled": "other",
    }
    grace_cutoff = now.timestamp() - bluesky_state.FOLLOW_RESPONSE_GRACE_PERIOD_SECONDS
    source_counts = Counter(
        source_names.get(str(entry.get("source") or ""), "other")
        for entry in state.get("follow_grace", {}).get("entries", [])
        if float(entry.get("followed_at") or 0) > grace_cutoff
    )
    runs = []
    for run in (workflow_activity or {}).get("runs", []):
        if run.get("workflow") != "bluesky_unfollow" or "processed" not in run:
            continue
        runs.append(
            {
                "created_at": run.get("created_at"),
                "eligible": max(0, int(run.get("eligible") or 0)),
                "processed": max(0, int(run.get("processed") or 0)),
                "unfollowed": max(0, int(run.get("unfollows") or 0)),
                "failed": max(0, int(run.get("failed") or 0)),
                "missing_records": max(0, int(run.get("missing_uri") or 0)),
                "stopped_early": bool(run.get("stopped_early")),
            }
        )
    return {
        "window_days": WORKFLOW_WINDOW_DAYS,
        "response_window": {
            "days": bluesky_state.FOLLOW_RESPONSE_GRACE_PERIOD_DAYS,
            "active": sum(source_counts.values()),
            "by_source": {
                source: source_counts[source]
                for source in ("discovery", "interaction", "other")
            },
        },
        "unfollow": {
            "completed_runs": len(runs),
            "eligible": sum(run["eligible"] for run in runs),
            "processed": sum(run["processed"] for run in runs),
            "unfollowed": sum(run["unfollowed"] for run in runs),
            "failed": sum(run["failed"] for run in runs),
            "missing_records": sum(run["missing_records"] for run in runs),
            "cap_remaining": sum(
                max(0, run["eligible"] - run["processed"]) for run in runs
            ),
            "stopped_early_runs": sum(run["stopped_early"] for run in runs),
            "runs": runs,
        },
    }


def _reconstructed_snapshots(
    current: dict, state: dict, workflow_activity: dict | None, now: datetime
) -> list[dict]:
    if not workflow_activity:
        return []
    coverage_value = workflow_activity.get("coverage_start")
    if not coverage_value:
        return []
    coverage_start = datetime.fromisoformat(coverage_value.replace("Z", "+00:00"))
    oldest_day = max(
        (now - timedelta(days=WORKFLOW_WINDOW_DAYS)).date(), coverage_start.date()
    )
    posts, follows, unfollows = _activity_by_day(state, workflow_activity)
    following_total = current["following"]
    post_total = current["profile_posts"]
    snapshots = []
    day = now.date()
    while day >= oldest_day:
        day_key = day.isoformat()
        if day != now.date():
            snapshots.append(
                {
                    "period_start": f"{day_key}T23:59:59+00:00",
                    "collected_at": f"{day_key}T23:59:59+00:00",
                    "followers": None,
                    "following": max(0, following_total),
                    "profile_posts": max(0, post_total),
                    "source": "workflow_history",
                }
            )
        following_total -= follows[day_key] - unfollows[day_key]
        post_total -= posts[day_key]
        day -= timedelta(days=1)
    return snapshots


def _period_start(now: datetime) -> str:
    bucket_hour = now.hour - (now.hour % 6)
    return now.replace(hour=bucket_hour, minute=0, second=0, microsecond=0).isoformat()


def _normalise_existing(existing: dict | None) -> dict:
    if existing is None:
        return {"schema_version": SCHEMA_VERSION, "snapshots": []}
    if existing.get("schema_version") not in {1, 2, 3, 4, 5, 6, SCHEMA_VERSION}:
        raise ValueError("Unsupported dashboard metrics schema version")
    if not isinstance(existing.get("snapshots"), list):
        raise ValueError("Dashboard metrics snapshots must be a list")
    existing["schema_version"] = SCHEMA_VERSION
    return existing


def _engagement_momentum(snapshots: list[dict], now: datetime) -> dict:
    sampled = [
        item
        for item in snapshots
        if item.get("source") == "bluesky_snapshot"
        and isinstance(item.get("engagement_total"), int)
        and item.get("collected_at")
    ]
    current = sampled[-1] if sampled else None
    deltas = {}
    for days in (7, 30):
        cutoff = now - timedelta(days=days)
        baseline = next(
            (
                item
                for item in reversed(sampled)
                if datetime.fromisoformat(item["collected_at"].replace("Z", "+00:00"))
                <= cutoff
            ),
            None,
        )
        deltas[str(days)] = (
            current["engagement_total"] - baseline["engagement_total"]
            if current and baseline
            else None
        )
    return {
        "basis": "visible_joke_snapshot_total",
        "deltas": deltas,
    }


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
        reason_counts = failure.get("reason_counts", {})
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
                "rejection_counts": {
                    reason: int(reason_counts.get(reason) or 0)
                    for reason in bluesky_state.PROVIDER_FAILURE_REASONS
                },
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


def _daily_schedule_times(cron: str) -> list[tuple[int, int]]:
    parts = cron.split()
    if len(parts) != 5 or parts[2:] != ["*", "*", "*"]:
        raise ValueError("Posting schedule must be a daily five-field cron")

    def _values(field: str, maximum: int) -> list[int]:
        if field == "*":
            return list(range(maximum + 1))
        if field.startswith("*/"):
            step = int(field[2:])
            if step <= 0:
                raise ValueError("Posting schedule step must be positive")
            return list(range(0, maximum + 1, step))
        values = sorted({int(value) for value in field.split(",")})
        if not values or any(value < 0 or value > maximum for value in values):
            raise ValueError("Posting schedule contains an out-of-range value")
        return values

    minutes = _values(parts[0], 59)
    hours = _values(parts[1], 23)
    return [(hour, minute) for hour in hours for minute in minutes]


def _posting_delivery(state: dict, cron: str, now: datetime) -> dict:
    schedule_times = _daily_schedule_times(cron)
    match_window = timedelta(hours=POSTING_SLOT_MATCH_HOURS)
    published_at = sorted(
        datetime.fromtimestamp(float(item["ts"]), tz=timezone.utc)
        for item in state.get("posted_jokes", [])
        if item.get("ts") is not None
    )

    def _slots(start: datetime, end: datetime) -> list[datetime]:
        slots = []
        day = start
        while day < end:
            slots.extend(
                day.replace(hour=hour, minute=minute) for hour, minute in schedule_times
            )
            day += timedelta(days=1)
        return slots

    def _summarise(slots: list[datetime]) -> dict:
        delivered = 0
        delayed = 0
        publication_index = 0
        for slot in slots:
            while (
                publication_index < len(published_at)
                and published_at[publication_index] < slot
            ):
                publication_index += 1
            if (
                publication_index < len(published_at)
                and published_at[publication_index] <= slot + match_window
            ):
                delivered += 1
                if published_at[publication_index] > slot + timedelta(minutes=30):
                    delayed += 1
                publication_index += 1
        expected = len(slots)
        return {
            "expected": expected,
            "delivered": delivered,
            "missed": expected - delivered,
            "delayed": delayed,
            "delivery_rate": round(delivered * 100 / expected, 1) if expected else None,
        }

    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    windows = {
        str(days): _summarise(_slots(today - timedelta(days=days), today))
        for days in POSTING_DELIVERY_WINDOWS
    }
    closed_slots = [
        slot
        for slot in _slots(today - timedelta(days=max(POSTING_DELIVERY_WINDOWS)), now)
        if slot + match_window <= now
    ]
    streak = 0
    for slot in reversed(closed_slots):
        if any(slot <= published <= slot + match_window for published in published_at):
            streak += 1
        else:
            break
    return {
        "schedule": cron,
        "timezone": "UTC",
        "match_window_hours": POSTING_SLOT_MATCH_HOURS,
        "current_streak": streak,
        "windows": windows,
    }


def _daily_schedule_interval_hours(cron: str) -> float | None:
    try:
        schedule_times = _daily_schedule_times(cron)
    except (TypeError, ValueError):
        return None
    minutes = sorted(hour * 60 + minute for hour, minute in schedule_times)
    if not minutes:
        return None
    gaps = [right - left for left, right in zip(minutes, minutes[1:])]
    gaps.append(24 * 60 - minutes[-1] + minutes[0])
    return round(max(gaps) / 60, 2)


def _workflow_duration_seconds(run: dict) -> int | None:
    created_at = run.get("created_at")
    updated_at = run.get("updated_at")
    if not created_at or not updated_at or run.get("status") != "completed":
        return None
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    if updated < created:
        return None
    return int((updated - created).total_seconds())


def _workflow_metrics(workflow_runs: list[dict], now: datetime) -> dict:
    schedules = bluesky_config.get_workflow_schedule_config()
    grouped = {
        name: {
            "name": name,
            "runs": 0,
            "successful": 0,
            "failed": 0,
            "cancelled": 0,
            "last_run_at": None,
            "last_status": None,
            "last_conclusion": None,
            "latest_duration_seconds": None,
            "median_duration_seconds": None,
            "expected_interval_hours": _daily_schedule_interval_hours(
                schedules.get(name, "")
            ),
        }
        for name in TRACKED_WORKFLOWS
    }
    durations = {name: [] for name in TRACKED_WORKFLOWS}
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
        duration = _workflow_duration_seconds(run)
        if created_at and (
            summary["last_run_at"] is None or created_at > summary["last_run_at"]
        ):
            summary["last_run_at"] = created_at
            summary["last_status"] = run.get("status")
            summary["last_conclusion"] = conclusion
            summary["latest_duration_seconds"] = duration
        if duration is not None:
            durations[name].append(duration)

    for name, values in durations.items():
        if values:
            grouped[name]["median_duration_seconds"] = int(median(values))

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


def _operational_alerts(
    automation: dict, providers: dict, posting_delivery: dict, now: datetime
) -> list[dict]:
    alerts = []
    recent_cutoff = now - timedelta(hours=24)
    for workflow in automation["workflows"]:
        last_run_at = workflow.get("last_run_at")
        expected_interval = workflow.get("expected_interval_hours")
        if (
            workflow["name"] in CORE_WORKFLOWS
            and expected_interval
            and (
                not last_run_at
                or datetime.fromisoformat(last_run_at.replace("Z", "+00:00"))
                < now - timedelta(hours=expected_interval + 2)
            )
        ):
            alerts.append(
                {
                    "level": "attention",
                    "kind": "workflow_overdue",
                    "workflow": workflow["name"],
                }
            )
        if (
            workflow["name"] in CORE_WORKFLOWS
            and workflow.get("last_conclusion") == "failure"
            and last_run_at
            and datetime.fromisoformat(last_run_at.replace("Z", "+00:00"))
            >= recent_cutoff
        ):
            alerts.append(
                {
                    "level": "attention",
                    "kind": "workflow_failure",
                    "workflow": workflow["name"],
                }
            )
    unhealthy = sum(
        provider.get("configured") is not False and provider.get("healthy") is False
        for provider in providers["providers"]
    )
    if unhealthy:
        alerts.append(
            {
                "level": "attention",
                "kind": "provider_health",
                "count": unhealthy,
            }
        )
    missed = posting_delivery["windows"]["7"]["missed"]
    if missed:
        alerts.append(
            {
                "level": "attention",
                "kind": "posting_delivery",
                "count": missed,
                "window_days": 7,
            }
        )
    return alerts


def collect_metrics(
    actor: str,
    state: dict,
    existing: dict | None = None,
    session=None,
    now: datetime | None = None,
    workflow_runs: list[dict] | None = None,
    workflow_activity: dict | None = None,
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
        "engagement_total": engagement_total,
        "source": "bluesky_snapshot",
    }
    snapshots = [
        item
        for item in existing["snapshots"]
        if item.get("source") != "workflow_history"
        and item.get("period_start") != snapshot["period_start"]
    ]
    snapshots.append(snapshot)
    existing_days = {
        datetime.fromisoformat(item["collected_at"].replace("Z", "+00:00")).date()
        for item in snapshots
    }
    snapshots.extend(
        item
        for item in _reconstructed_snapshots(current, state, workflow_activity, now)
        if datetime.fromisoformat(item["collected_at"]).date() not in existing_days
    )
    snapshots.sort(key=lambda item: item["period_start"])

    providers = _provider_metrics(state, joke_posts)
    automation = _workflow_metrics(workflow_runs or [], now)
    posting_delivery = _posting_delivery(
        state,
        bluesky_config.get_workflow_schedule_config()["bluesky_post_joke"],
        now,
    )
    automation["alerts"] = _operational_alerts(
        automation, providers, posting_delivery, now
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
        "daily_activity": _daily_activity(state, workflow_activity),
        "discovery_activity": _discovery_metrics(workflow_activity),
        "social_activity": _social_activity_metrics(workflow_activity),
        "moderation_activity": _moderation_metrics(workflow_activity),
        "engagement_momentum": _engagement_momentum(snapshots, now),
        "provider_pressure": _provider_pressure_metrics(workflow_activity, now),
        "network_maintenance": _network_maintenance_metrics(
            state, workflow_activity, now
        ),
        "workflow_activity": workflow_activity
        or {
            "window_days": WORKFLOW_WINDOW_DAYS,
            "coverage_start": now.isoformat(),
            "expired_before": None,
            "runs": [],
        },
        "providers": providers,
        "posting_delivery": posting_delivery,
        "automation": automation,
        "top_posts": _top_post_summaries(joke_posts, profile["handle"]),
        "top_posts_by_window": _top_posts_by_window(joke_posts, profile["handle"], now),
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
    existing = _load_existing()
    workflow_activity = collect_workflow_activity(
        session,
        repository,
        os.getenv("GITHUB_TOKEN"),
        workflow_runs,
        existing,
        now,
    )
    metrics = collect_metrics(
        actor,
        bluesky_state.load_state(),
        existing,
        session=session,
        now=now,
        workflow_runs=workflow_runs,
        workflow_activity=workflow_activity,
    )
    _write_metrics(metrics)
    print(
        f"Dashboard metrics updated for @{metrics['account']['handle']} "
        f"at {metrics['generated_at']}."
    )


if __name__ == "__main__":
    main()
