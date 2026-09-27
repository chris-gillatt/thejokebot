"""Workflow-analysis domain for dashboard metrics collection."""

from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime, timedelta, timezone
from statistics import median

import requests

from thejokebot import config as runtime_config
from thejokebot.commands import dashboard_history
from thejokebot.runtime import retry_network_call

GITHUB_API_BASE = "https://api.github.com"
_UTC_OFFSET = "+00:00"
MAX_WORKFLOW_PAGES = 20
MAX_WORKFLOW_LOG_BYTES = 25 * 1024 * 1024
MAX_WORKFLOW_LOG_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
WORKFLOW_WINDOW_DAYS = dashboard_history.WORKFLOW_WINDOW_DAYS
TRACKED_WORKFLOWS = dashboard_history.TRACKED_WORKFLOWS
CORE_WORKFLOWS = {
    "bluesky_dashboard",
    "bluesky_follows_and_likes",
    "bluesky_post_joke",
    "bluesky_process_reports",
}
ACTIVITY_WORKFLOWS = {
    "bluesky_follow_fellows",
    "bluesky_follows_and_likes",
    "bluesky_manage_starter_pack",
    "bluesky_post_joke",
    "bluesky_process_reports",
    "bluesky_unfollow",
}


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
    *,
    retry_call=retry_network_call,
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

        payload = retry_call(
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
    session,
    repository: str,
    run_id: int,
    token: str | None,
    *,
    retry_call=retry_network_call,
) -> str:
    def _request():
        response = session.get(
            f"{GITHUB_API_BASE}/repos/{repository}/actions/runs/{run_id}/logs",
            headers=_github_headers(token),
            timeout=30,
        )
        response.raise_for_status()
        return response.content

    archive_bytes = retry_call(
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
        r"Provider summary: attempts=(\d+), "
        r"(?:starting_provider=([a-z0-9_-]+), )?"
        r"successful_source=([a-z0-9_-]+), "
        r"fallthrough=(true|false), static_fallback=(true|false), "
        r"duplicate=(\d+), too_long=(\d+), network_error=(\d+), "
        r"provider_error=(\d+), posted=(true|false)\.",
        log_text,
    )
    if not summaries:
        return None
    (
        attempts,
        starting_provider,
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
        "starting_provider": starting_provider or None,
        "successful_source": successful_source,
        "fallthrough": fallthrough == "true",
        "static_fallback": static_fallback == "true",
        "duplicate": int(duplicate),
        "too_long": int(too_long),
        "network_error": int(network_error),
        "provider_error": int(provider_error),
        "posted": posted == "true",
    }


def _social_summary_counts(plain_text: str) -> dict:
    prefix = "Social summary: "
    suffix = ", dry_run=false."
    summaries = []
    for line in plain_text.splitlines():
        start = line.find(prefix)
        if start >= 0 and line.endswith(suffix):
            summaries.append(line[start + len(prefix) : -len(suffix)])
    if not summaries:
        return {}
    values = {}
    for assignment in summaries[-1].split(", "):
        field, separator, value = assignment.partition("=")
        if not separator or not field.replace("_", "").islower() or not value.isdigit():
            return {}
        values[field] = int(value)
    required = {
        "follow_back_candidates",
        "follow_back_added",
        "protected",
        "interaction_candidates",
        "interaction_eligible",
        "interaction_added",
        "interactions_liked",
        "failed",
    }
    return values if required.issubset(values) else {}


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
        values = _social_summary_counts(plain_text)
        if values:
            return {
                "follows": values["follow_back_added"] + values["interaction_added"],
                "unfollows": 0,
                "social_summary_observed": True,
                **values,
            }
        follows = len(re.findall(r"\bFollowed (?:interactor )?did:[^\s]+", plain_text))
        return {
            "follows": follows,
            "unfollows": 0,
            "social_summary_observed": False,
        }
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


def _workflow_run_candidate(
    run: dict, cutoff: datetime, expired_before: datetime | None
):
    workflow_name = str(run.get("name") or "")
    created_at = run.get("created_at")
    run_id = run.get("id")
    if (
        workflow_name not in ACTIVITY_WORKFLOWS
        or run.get("conclusion") != "success"
        or not created_at
        or run_id is None
    ):
        return None
    created = datetime.fromisoformat(created_at.replace("Z", _UTC_OFFSET))
    if created < cutoff or (expired_before and created <= expired_before):
        return None
    return workflow_name, created_at, int(run_id), created


def _cached_workflow_run_complete(cached: dict | None, workflow_name: str) -> bool:
    required_fields = {
        "bluesky_follow_fellows": ("selected", "failed"),
        "bluesky_follows_and_likes": ("social_summary_observed",),
        "bluesky_unfollow": ("processed",),
        "bluesky_process_reports": ("proposals",),
        "bluesky_post_joke": ("provider_attempts",),
    }
    return bool(
        cached
        and cached.get("workflow") == workflow_name
        and all(field in cached for field in required_fields.get(workflow_name, ()))
    )


def _collect_run_activity(
    session,
    repository,
    token,
    workflow_name,
    run_id,
    created,
    expired_before,
    *,
    fetch_logs=None,
):
    if fetch_logs is None:
        fetch_logs = fetch_workflow_run_logs
    try:
        counts = _workflow_activity_counts(
            workflow_name,
            fetch_logs(session, repository, run_id, token),
        )
    except (
        OSError,
        ValueError,
        zipfile.BadZipFile,
        requests.RequestException,
    ) as exc:
        print(f"Warning: could not collect activity from workflow run {run_id}: {exc}")
        is_expired = (
            isinstance(exc, requests.HTTPError)
            and exc.response is not None
            and exc.response.status_code == 410
        )
        if is_expired and (expired_before is None or created > expired_before):
            expired_before = created
        return None, created, expired_before
    if counts is None:
        print(f"Warning: workflow run {run_id} has no recognised activity summary")
        return None, created, expired_before
    return counts, None, expired_before


def _previous_workflow_activity(existing: dict | None, cutoff: datetime) -> tuple:
    previous_activity = (existing or {}).get("workflow_activity", {})
    previous_expired_value = previous_activity.get("expired_before")
    expired_before = (
        datetime.fromisoformat(previous_expired_value.replace("Z", _UTC_OFFSET))
        if previous_expired_value
        else None
    )
    cached_runs = {
        int(item["id"]): item
        for item in previous_activity.get("runs", [])
        if item.get("id") is not None
        and item.get("created_at")
        and datetime.fromisoformat(item["created_at"].replace("Z", _UTC_OFFSET))
        >= cutoff
    }
    return expired_before, cached_runs


def collect_workflow_activity(
    session,
    repository: str,
    token: str | None,
    workflow_runs: list[dict],
    existing: dict | None,
    now: datetime,
    *,
    fetch_logs=None,
) -> dict:
    if fetch_logs is None:
        fetch_logs = fetch_workflow_run_logs
    cutoff = now - timedelta(days=WORKFLOW_WINDOW_DAYS)
    expired_before, cached_runs = _previous_workflow_activity(existing, cutoff)
    unavailable_at: list[datetime] = []

    for run in workflow_runs:
        candidate = _workflow_run_candidate(run, cutoff, expired_before)
        if candidate is None:
            continue
        workflow_name, created_at, run_id, created = candidate
        attempt = int(run.get("run_attempt") or 1)
        cached = cached_runs.get(run_id)
        cached_attempt_matches = cached and int(cached.get("attempt") or 1) == attempt
        if cached_attempt_matches and _cached_workflow_run_complete(
            cached, workflow_name
        ):
            continue
        counts, unavailable, expired_before = _collect_run_activity(
            session,
            repository,
            token,
            workflow_name,
            run_id,
            created,
            expired_before,
            fetch_logs=fetch_logs,
        )
        if unavailable is not None:
            unavailable_at.append(unavailable)
            continue
        if counts is None:
            continue
        cached_runs[run_id] = {
            "id": run_id,
            "attempt": attempt,
            "workflow": workflow_name,
            "created_at": created_at,
            **counts,
        }

    coverage_candidates = [cutoff, *unavailable_at]
    if expired_before is not None:
        coverage_candidates.append(expired_before)
    coverage_start = max(coverage_candidates)
    return {
        "window_days": WORKFLOW_WINDOW_DAYS,
        "coverage_start": coverage_start.isoformat(),
        "expired_before": expired_before.isoformat() if expired_before else None,
        "runs": sorted(cached_runs.values(), key=lambda item: item["created_at"]),
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
    created = datetime.fromisoformat(created_at.replace("Z", _UTC_OFFSET))
    updated = datetime.fromisoformat(updated_at.replace("Z", _UTC_OFFSET))
    if updated < created:
        return None
    return int((updated - created).total_seconds())


def _update_workflow_summary(summary: dict, run: dict) -> int | None:
    summary["runs"] += 1
    conclusion = run.get("conclusion")
    conclusion_field = (
        {
            "success": "successful",
            "failure": "failed",
            "cancelled": "cancelled",
        }.get(conclusion)
        if isinstance(conclusion, str)
        else None
    )
    if conclusion_field:
        summary[conclusion_field] += 1

    created_at = run.get("created_at")
    duration = _workflow_duration_seconds(run)
    if created_at and (
        summary["last_run_at"] is None or created_at > summary["last_run_at"]
    ):
        summary["last_run_at"] = created_at
        summary["last_status"] = run.get("status")
        summary["last_conclusion"] = conclusion
        summary["latest_duration_seconds"] = duration
    return duration


def _workflow_metrics(workflow_runs: list[dict], now: datetime) -> dict:
    schedules = runtime_config.get_workflow_schedule_config()
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
        duration = _update_workflow_summary(summary, run)
        if duration is not None:
            durations[name].append(duration)

    for name, values in durations.items():
        if values:
            grouped[name]["median_duration_seconds"] = int(median(values))
        completed_runs = sorted(
            (
                run
                for run in workflow_runs
                if run.get("name") == name and run.get("status") == "completed"
            ),
            key=lambda run: str(run.get("created_at") or ""),
            reverse=True,
        )
        grouped[name]["consecutive_failures"] = 0
        for run in completed_runs:
            if run.get("conclusion") != "failure":
                break
            grouped[name]["consecutive_failures"] += 1

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


def _mutation_persistence_alerts(
    workflow_runs: list[dict], workflow_activity: dict | None, now: datetime
) -> list[dict]:
    activity_by_id = {
        int(item["id"]): item
        for item in (workflow_activity or {}).get("runs", [])
        if item.get("id") is not None
    }
    mutation_fields = (
        "posted",
        "follows",
        "unfollows",
        "deleted",
        "acknowledged",
        "interactions_liked",
        "joke_replies",
    )
    alerts = []
    cutoff = now - timedelta(hours=24)
    for run in workflow_runs:
        created_at = run.get("created_at")
        if (
            run.get("conclusion") != "failure"
            or run.get("id") is None
            or not created_at
            or datetime.fromisoformat(created_at.replace("Z", _UTC_OFFSET)) < cutoff
        ):
            continue
        activity = activity_by_id.get(int(run["id"]), {})
        if any(int(activity.get(field) or 0) > 0 for field in mutation_fields):
            alerts.append(
                {
                    "level": "urgent",
                    "kind": "mutation_persistence_uncertain",
                    "workflow": run.get("name"),
                    "run_id": int(run["id"]),
                }
            )
    return alerts


def _operational_alerts(
    automation: dict,
    providers: dict,
    posting_delivery: dict,
    now: datetime,
    *,
    state: dict | None = None,
    workflow_runs: list[dict] | None = None,
    workflow_activity: dict | None = None,
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
                or datetime.fromisoformat(last_run_at.replace("Z", _UTC_OFFSET))
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
            and datetime.fromisoformat(last_run_at.replace("Z", _UTC_OFFSET))
            >= recent_cutoff
        ):
            alerts.append(
                {
                    "level": "attention",
                    "kind": "workflow_failure",
                    "workflow": workflow["name"],
                }
            )
        if workflow.get("consecutive_failures", 0) >= 2:
            alerts.append(
                {
                    "level": "urgent",
                    "kind": "workflow_failure_streak",
                    "workflow": workflow["name"],
                    "count": workflow["consecutive_failures"],
                }
            )
    alerts.extend(
        _mutation_persistence_alerts(workflow_runs or [], workflow_activity, now)
    )
    checkpoint = (state or {}).get("joke_requests", {}).get("last_checked_at")
    joke_schedule = next(
        (
            item.get("expected_interval_hours")
            for item in automation["workflows"]
            if item["name"] == "bluesky_follows_and_likes"
        ),
        None,
    )
    if joke_schedule and (
        checkpoint is None
        or datetime.fromtimestamp(float(checkpoint), timezone.utc)
        < now - timedelta(hours=float(joke_schedule) + 2)
    ):
        alerts.append(
            {
                "level": "attention",
                "kind": "joke_request_checkpoint_stale",
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
