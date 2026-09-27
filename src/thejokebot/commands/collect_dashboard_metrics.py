"""Collect aggregate public Bluesky metrics for the static dashboard."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import requests

from thejokebot import state as bot_state
from thejokebot.commands import dashboard_metrics
from thejokebot.commands import dashboard_history
from thejokebot.commands import dashboard_workflows
from thejokebot.runtime import retry_network_call

PUBLIC_API_BASE = dashboard_metrics.PUBLIC_API_BASE
METRICS_FILE = dashboard_history.METRICS_FILE
SCHEMA_VERSION = dashboard_history.SCHEMA_VERSION
MAX_FEED_PAGES = dashboard_metrics.MAX_FEED_PAGES
MAX_FEED_RUNTIME_SECONDS = dashboard_metrics.MAX_FEED_RUNTIME_SECONDS
WORKFLOW_WINDOW_DAYS = dashboard_history.WORKFLOW_WINDOW_DAYS
TOP_POST_LIMIT = dashboard_metrics.TOP_POST_LIMIT
PROVIDER_COMPARISON_MIN_POSTS = dashboard_metrics.PROVIDER_COMPARISON_MIN_POSTS
POSTING_DELIVERY_WINDOWS = dashboard_metrics.POSTING_DELIVERY_WINDOWS
POSTING_SLOT_MATCH_HOURS = dashboard_metrics.POSTING_SLOT_MATCH_HOURS
ENGAGEMENT_FIELDS = dashboard_metrics.ENGAGEMENT_FIELDS


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
    return dashboard_metrics.fetch_profile(session, actor, request_json=_request_json)


def fetch_post(session, uri: str) -> dict:
    return dashboard_metrics.fetch_post(session, uri, request_json=_request_json)


def fetch_original_posts(
    session,
    actor_did: str,
    max_pages: int = MAX_FEED_PAGES,
    max_runtime_seconds: int = MAX_FEED_RUNTIME_SECONDS,
) -> list[dict]:
    return dashboard_metrics.fetch_original_posts(
        session,
        actor_did,
        max_pages=max_pages,
        max_runtime_seconds=max_runtime_seconds,
        request_json=_request_json,
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


def collect_metrics(
    actor: str,
    state: dict,
    existing: dict | None = None,
    session=None,
    now: datetime | None = None,
    workflow_runs: list[dict] | None = None,
    workflow_activity: dict | None = None,
) -> dict:
    return dashboard_metrics.collect_metrics(
        actor,
        state,
        existing=existing,
        session=session,
        now=now,
        workflow_runs=workflow_runs,
        workflow_activity=workflow_activity,
        fetch_profile_call=fetch_profile,
        fetch_post_call=fetch_post,
        fetch_original_posts_call=fetch_original_posts,
    )


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
