"""Collect aggregate public Bluesky metrics for the static dashboard."""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from statistics import median

import requests

from thejokebot import config as runtime_config
from thejokebot import state as bot_state
from thejokebot.commands import dashboard_history
from thejokebot.commands import dashboard_workflows
from thejokebot.runtime import retry_network_call

PUBLIC_API_BASE = "https://public.api.bsky.app/xrpc"
_UTC_OFFSET = "+00:00"
METRICS_FILE = dashboard_history.METRICS_FILE
SCHEMA_VERSION = dashboard_history.SCHEMA_VERSION
MAX_FEED_PAGES = 100
MAX_FEED_RUNTIME_SECONDS = 120
WORKFLOW_WINDOW_DAYS = dashboard_history.WORKFLOW_WINDOW_DAYS
TOP_POST_LIMIT = 6
PROVIDER_COMPARISON_MIN_POSTS = 30
POSTING_DELIVERY_WINDOWS = (7, 30)
POSTING_SLOT_MATCH_HOURS = 2
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
    max_pages: int = dashboard_workflows.MAX_WORKFLOW_PAGES,
) -> list[dict]:
    return dashboard_workflows.fetch_workflow_runs(
        session,
        repository,
        token,
        now,
        max_pages=max_pages,
        retry_call=retry_network_call,
    )


def fetch_workflow_run_logs(
    session, repository: str, run_id: int, token: str | None
) -> str:
    return dashboard_workflows.fetch_workflow_run_logs(
        session,
        repository,
        run_id,
        token,
        retry_call=retry_network_call,
    )


def collect_workflow_activity(
    session,
    repository: str,
    token: str | None,
    workflow_runs: list[dict],
    existing: dict | None,
    now: datetime,
) -> dict:
    return dashboard_workflows.collect_workflow_activity(
        session,
        repository,
        token,
        workflow_runs,
        existing,
        now,
        fetch_logs=fetch_workflow_run_logs,
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
            created = datetime.fromisoformat(created_at.replace("Z", _UTC_OFFSET))
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
            datetime.fromisoformat(created_at.replace("Z", _UTC_OFFSET))
            .date()
            .isoformat()
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
                "joke_replies": max(0, int(run.get("joke_replies") or 0)),
                "starter_pack_follows": max(
                    0, int(run.get("starter_pack_follows") or 0)
                ),
                "starter_pack_scan_complete": max(
                    0, int(run.get("starter_pack_scan_complete") or 0)
                ),
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
        "joke_replies",
        "starter_pack_follows",
        "starter_pack_scan_complete",
        "failed",
    )
    return {
        "window_days": WORKFLOW_WINDOW_DAYS,
        "completed_runs": len(runs),
        **{field: sum(run[field] for run in runs) for field in fields},
        "runs": runs,
    }


def _follower_growth(snapshots: list[dict], now: datetime) -> dict:
    sampled = [
        item
        for item in snapshots
        if item.get("source") == "bluesky_snapshot"
        and isinstance(item.get("followers"), int)
        and item.get("collected_at")
    ]
    current = sampled[-1] if sampled else None
    windows = {}
    for days in (7, 30):
        cutoff = now - timedelta(days=days)
        baseline = next(
            (
                item
                for item in reversed(sampled)
                if datetime.fromisoformat(
                    item["collected_at"].replace("Z", _UTC_OFFSET)
                )
                <= cutoff
            ),
            None,
        )
        windows[str(days)] = (
            current["followers"] - baseline["followers"]
            if current and baseline
            else None
        )
    return windows


def _cohort_checkpoint_metrics(totals: dict, checkpoint: str, pending_due: int) -> dict:
    checkpoint_totals = totals.get("checkpoints", {}).get(checkpoint, {})
    observed = max(0, int(checkpoint_totals.get("observed", 0)))
    still_following = max(0, int(checkpoint_totals.get("still_following", 0)))
    return {
        "observed": observed,
        "still_following": still_following,
        "rate": round(still_following * 100 / observed, 1) if observed else None,
        "pending_due": pending_due,
    }


def _cohort_coverage_started_at(value) -> str | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    return value if isinstance(value, str) else None


def _cohort_metrics(state: dict, now: datetime) -> dict:
    cohort_state = state.get("follow_tracking", {}).get("acquisition_cohorts", {})
    pending_due = Counter()
    now_timestamp = now.timestamp()
    for member in cohort_state.get("members", {}).values():
        source = str(member.get("source") or "")
        month = str(member.get("cohort_month") or "")
        acquired_at = float(member.get("acquired_at") or 0)
        checkpoints = member.get("checkpoints", {})
        if source not in bot_state.ACQUISITION_COHORT_SOURCES or not month:
            continue
        for days in bot_state.ACQUISITION_COHORT_CHECKPOINT_DAYS:
            if (
                checkpoints.get(str(days)) is None
                and now_timestamp >= acquired_at + days * 24 * 60 * 60
            ):
                pending_due[(month, source, str(days))] += 1

    periods = []
    for month, source_totals in sorted(cohort_state.get("cohorts", {}).items()):
        for source in bot_state.ACQUISITION_COHORT_SOURCES:
            totals = source_totals.get(source)
            if not isinstance(totals, dict):
                continue
            checkpoints = {}
            for days in bot_state.ACQUISITION_COHORT_CHECKPOINT_DAYS:
                checkpoint = str(days)
                checkpoints[checkpoint] = _cohort_checkpoint_metrics(
                    totals,
                    checkpoint,
                    pending_due[(month, source, checkpoint)],
                )
            periods.append(
                {
                    "month": month,
                    "source": source,
                    "acquired": max(0, int(totals.get("acquired") or 0)),
                    "checkpoints": checkpoints,
                }
            )

    return {
        "checkpoint_days": list(bot_state.ACQUISITION_COHORT_CHECKPOINT_DAYS),
        "coverage_started_at": _cohort_coverage_started_at(
            cohort_state.get("coverage_started_at")
        ),
        "periods": periods,
    }


def _audience_growth_metrics(
    state: dict,
    snapshots: list[dict],
    discovery: dict,
    social: dict,
    now: datetime,
) -> dict:
    source_values = {
        "followback": (
            "candidates",
            int(social.get("follow_back_candidates") or 0),
            int(social.get("follow_back_added") or 0),
        ),
        "interaction": (
            "eligible",
            int(social.get("interaction_eligible") or 0),
            int(social.get("interaction_added") or 0),
        ),
        "discovery": (
            "selected",
            int(discovery.get("selected") or 0),
            int(discovery.get("followed") or 0),
        ),
    }
    sources = {}
    for source, (denominator, considered, acquired) in source_values.items():
        sources[source] = {
            "denominator": denominator,
            "considered": considered,
            "acquired": acquired,
            "success_rate": round(acquired * 100 / considered, 1)
            if considered
            else None,
        }
    return {
        "window_days": WORKFLOW_WINDOW_DAYS,
        "net_followers": _follower_growth(snapshots, now),
        "sources": sources,
        "cohorts": _cohort_metrics(state, now),
        "coverage": {
            "social_started_at": min(
                (
                    run["created_at"]
                    for run in social.get("runs", [])
                    if run.get("created_at")
                ),
                default=None,
            ),
            "discovery_started_at": discovery.get("coverage_start"),
        },
    }


def _starter_pack_attribution_metrics(state: dict, now: datetime) -> dict:
    attribution = state.get("follow_tracking", {}).get("starter_pack_attribution", {})
    cutoffs = {
        "7": (now - timedelta(days=6)).date().isoformat(),
        "30": (now - timedelta(days=WORKFLOW_WINDOW_DAYS - 1)).date().isoformat(),
    }
    packs = []
    for pack_uri, pack in attribution.get("packs", {}).items():
        match = re.fullmatch(
            r"at://(?P<creator>[^/]+)/app\.bsky\.graph\.starterpack/(?P<rkey>[^/]+)",
            pack_uri,
        )
        if match is None:
            continue
        windows = {
            window: sum(
                max(0, int(count or 0))
                for date, count in pack.get("daily_counts", {}).items()
                if date >= cutoff
            )
            for window, cutoff in cutoffs.items()
        }
        if windows["30"] <= 0:
            continue
        packs.append(
            {
                "name": str(pack.get("name") or "Starter pack"),
                "creator_handle": str(pack.get("creator_handle") or ""),
                "url": (
                    "https://bsky.app/starter-pack/"
                    f"{match.group('creator')}/{match.group('rkey')}"
                ),
                "follows": windows["30"],
                "windows": windows,
            }
        )
    packs.sort(key=lambda pack: (-pack["follows"], pack["name"].casefold()))
    totals = {
        window: sum(pack["windows"][window] for pack in packs) for window in cutoffs
    }
    for pack in packs:
        pack["share_30_day"] = (
            round(pack["windows"]["30"] * 100 / totals["30"], 1)
            if totals["30"]
            else None
        )
    return {
        "window_days": WORKFLOW_WINDOW_DAYS,
        "coverage_started_at": attribution.get("coverage_started_at"),
        "last_checked_at": attribution.get("last_checked_at"),
        "total_follows": totals["30"],
        "windows": totals,
        "packs": packs,
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
                "starting_provider": run.get("starting_provider"),
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
            if datetime.fromisoformat(run["created_at"].replace("Z", _UTC_OFFSET))
            >= cutoff
        ]
        fallthroughs = sum(run["fallthrough"] for run in runs)
        attempts = sum(run["provider_attempts"] for run in runs)
        starts = Counter(
            run["starting_provider"] for run in runs if run["starting_provider"]
        )
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
            "starting_providers": dict(sorted(starts.items())),
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
    grace_cutoff = now.timestamp() - bot_state.FOLLOW_RESPONSE_GRACE_PERIOD_SECONDS
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
            "days": bot_state.FOLLOW_RESPONSE_GRACE_PERIOD_DAYS,
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
    coverage_start = datetime.fromisoformat(coverage_value.replace("Z", _UTC_OFFSET))
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
                    "period_start": f"{day_key}T23:59:59{_UTC_OFFSET}",
                    "collected_at": f"{day_key}T23:59:59{_UTC_OFFSET}",
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


def _normalise_existing(existing: dict | None) -> dict:
    if existing is None:
        return {"schema_version": SCHEMA_VERSION, "snapshots": []}
    if existing.get("schema_version") not in {
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        SCHEMA_VERSION,
    }:
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
                if datetime.fromisoformat(
                    item["collected_at"].replace("Z", _UTC_OFFSET)
                )
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
                if visible_posts >= PROVIDER_COMPARISON_MIN_POSTS
                else None,
                "fallthroughs": int(failure.get("count") or 0),
                "rejection_counts": {
                    reason: int(reason_counts.get(reason) or 0)
                    for reason in bot_state.PROVIDER_FAILURE_REASONS
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
        "minimum_comparison_posts": PROVIDER_COMPARISON_MIN_POSTS,
        "providers": providers,
    }


def _daily_schedule_times(cron: str) -> list[tuple[int, int]]:
    return dashboard_workflows._daily_schedule_times(cron)


def _posting_slots(
    start: datetime, end: datetime, schedule_times: list[tuple[int, int]]
) -> list[datetime]:
    slots = []
    day = start
    while day < end:
        slots.extend(
            day.replace(hour=hour, minute=minute) for hour, minute in schedule_times
        )
        day += timedelta(days=1)
    return slots


def _summarise_posting_slots(
    slots: list[datetime], published_at: list[datetime], match_window: timedelta
) -> dict:
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


def _posting_streak(
    slots: list[datetime], published_at: list[datetime], match_window: timedelta
) -> int:
    streak = 0
    for slot in reversed(slots):
        if not any(
            slot <= published <= slot + match_window for published in published_at
        ):
            break
        streak += 1
    return streak


def _posting_delivery(state: dict, cron: str, now: datetime) -> dict:
    schedule_times = dashboard_workflows._daily_schedule_times(cron)
    match_window = timedelta(hours=POSTING_SLOT_MATCH_HOURS)
    published_at = sorted(
        datetime.fromtimestamp(float(item["ts"]), tz=timezone.utc)
        for item in state.get("posted_jokes", [])
        if item.get("ts") is not None
    )

    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    windows = {
        str(days): _summarise_posting_slots(
            _posting_slots(today - timedelta(days=days), today, schedule_times),
            published_at,
            match_window,
        )
        for days in POSTING_DELIVERY_WINDOWS
    }
    closed_slots = [
        slot
        for slot in _posting_slots(
            today - timedelta(days=max(POSTING_DELIVERY_WINDOWS)), now, schedule_times
        )
        if slot + match_window <= now
    ]
    return {
        "schedule": cron,
        "timezone": "UTC",
        "match_window_hours": POSTING_SLOT_MATCH_HOURS,
        "current_streak": _posting_streak(closed_slots, published_at, match_window),
        "windows": windows,
    }


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
        "period_start": dashboard_history._period_start(now),
        "collected_at": now.isoformat(),
        "followers": current["followers"],
        "following": current["following"],
        "profile_posts": current["profile_posts"],
        "joke_posts": current["joke_posts"],
        "engagement": current["engagement"],
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
        datetime.fromisoformat(item["collected_at"].replace("Z", _UTC_OFFSET)).date()
        for item in snapshots
    }
    snapshots.extend(
        item
        for item in _reconstructed_snapshots(current, state, workflow_activity, now)
        if datetime.fromisoformat(item["collected_at"]).date() not in existing_days
    )
    snapshots.sort(key=lambda item: item["period_start"])

    providers = _provider_metrics(state, joke_posts)
    automation = dashboard_workflows._workflow_metrics(workflow_runs or [], now)
    posting_delivery = _posting_delivery(
        state,
        runtime_config.get_workflow_schedule_config()["bluesky_post_joke"],
        now,
    )
    automation["alerts"] = dashboard_workflows._operational_alerts(
        automation,
        providers,
        posting_delivery,
        now,
        state=state,
        workflow_runs=workflow_runs,
        workflow_activity=workflow_activity,
    )
    discovery_activity = _discovery_metrics(workflow_activity)
    social_activity = _social_activity_metrics(workflow_activity)

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
        "discovery_activity": discovery_activity,
        "social_activity": social_activity,
        "audience_growth": _audience_growth_metrics(
            state, snapshots, discovery_activity, social_activity, now
        ),
        "starter_pack_attribution": _starter_pack_attribution_metrics(state, now),
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
    dashboard_history._write_json(METRICS_FILE, metrics)


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
    history = dashboard_history._merge_history_partitions(
        dashboard_history._load_history_partitions(),
        dashboard_history._migrate_existing_history(existing),
    )
    collector_existing = dashboard_history._collector_existing(existing, history, now)
    workflow_activity = collect_workflow_activity(
        session,
        repository,
        os.getenv("GITHUB_TOKEN"),
        workflow_runs,
        collector_existing,
        now,
    )
    metrics = collect_metrics(
        actor,
        bot_state.load_state(),
        collector_existing,
        session=session,
        now=now,
        workflow_runs=workflow_runs,
        workflow_activity=workflow_activity,
    )
    history = dashboard_history._merge_history_partitions(
        history, dashboard_history._history_from_collection(metrics, workflow_runs)
    )
    dashboard_history._write_history(history, now, workflow_activity)
    _write_metrics(dashboard_history._compact_metrics(metrics, now))
    print(
        f"Dashboard metrics updated for @{metrics['account']['handle']} "
        f"at {metrics['generated_at']}."
    )


if __name__ == "__main__":
    main()
