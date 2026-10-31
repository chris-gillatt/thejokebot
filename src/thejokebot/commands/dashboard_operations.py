"""Sanitised operational investigation and component observations."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import requests

from thejokebot.paths import PROJECT_ROOT

CI_WORKFLOWS = frozenset(
    {
        "python_tests",
        "ruff_quality",
        "codeql",
        "validate_runtime_config",
        "pr_auto_merge",
    }
)
MAX_JOB_PAGES = 10


@lru_cache(maxsize=1)
def _step_names() -> frozenset[str]:
    names = set()
    for path in (PROJECT_ROOT / ".github" / "workflows").glob("*.yml"):
        for name in re.findall(r"^\s*- name: (.+)$", path.read_text(), re.MULTILINE):
            name = name.strip().strip("'\"")
            if "${{" not in name:
                names.add(name)
    return frozenset(names)


def sanitise_steps(steps: object) -> list[dict]:
    if not isinstance(steps, list):
        raise ValueError("Failed workflow steps must be a list")
    public = []
    for step in steps:
        if not isinstance(step, dict) or not {"number", "job_id"} <= step.keys():
            raise ValueError("Failed workflow step is missing its identity")
        number = step["number"]
        job_id = step["job_id"]
        if (
            type(number) is not int
            or number < 0
            or type(job_id) is not int
            or job_id <= 0
        ):
            raise ValueError("Invalid failed workflow step identity")
        name = step.get("name")
        public.append(
            {
                "number": number,
                "job_id": job_id,
                "name": name
                if isinstance(name, str) and name in _step_names()
                else f"Step {number} (name unavailable)",
            }
        )
    return public


def _job_steps(jobs: list) -> list[dict]:
    failed = []
    for job in jobs:
        if not isinstance(job, dict) or "id" not in job:
            raise ValueError("Invalid workflow job metadata")
        if job.get("conclusion") != "failure":
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            raise ValueError("Failed workflow job is missing step metadata")
        if any(not isinstance(step, dict) or "number" not in step for step in steps):
            raise ValueError("Invalid workflow step metadata")
        failures = [step for step in steps if step.get("conclusion") == "failure"]
        for step in failures or [{"number": 0}]:
            failed.append(
                {
                    "number": step["number"],
                    "job_id": job["id"],
                    "name": step.get("name"),
                }
            )
    return sanitise_steps(failed)


def fetch_failed_steps(
    session, repository, run_id, attempt, headers, retry_call
) -> list[dict]:
    failed = []
    for page in range(1, MAX_JOB_PAGES + 1):

        def request(page_number=page):
            response = session.get(
                f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/attempts/{attempt}/jobs",
                params={"per_page": 100, "page": page_number},
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()

        payload = retry_call(
            request, description=f"fetching failed steps for run {run_id}"
        )
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            raise ValueError("GitHub workflow jobs response is missing jobs")
        failed.extend(_job_steps(jobs))
        if len(jobs) < 100:
            return failed
    raise RuntimeError("Workflow jobs pagination exceeded its safety limit")


def enrich_runs(
    runs: list[dict], cached: list[dict], tracked: set, fetch_steps
) -> list[dict]:
    previous = {
        (item["id"], item.get("attempt", 1)): item
        for item in cached
        if item.get("failure_metadata") == "available"
    }
    enriched = []
    for run in runs:
        current = dict(run)
        if (
            run.get("name") in tracked
            and run.get("status") == "completed"
            and run.get("conclusion") == "failure"
        ):
            identity = (run["id"], int(run.get("run_attempt") or 1))
            stored = previous.get(identity)
            try:
                steps = stored.get("failed_steps") if stored else fetch_steps(*identity)
                current["failed_steps"] = sanitise_steps(steps)
                current["failure_metadata"] = "available"
            except (
                requests.RequestException,
                OSError,
                ValueError,
                RuntimeError,
            ) as exc:
                print(
                    f"Warning: failed-step metadata unavailable for run {run['id']}: {exc}"
                )
                current["failure_metadata"] = "unavailable"
        enriched.append(current)
    return enriched


def public_runs(runs: list[dict], tracked: set) -> list[dict]:
    public = []
    for run in runs:
        if run.get("name") not in tracked or not run.get("created_at"):
            continue
        record = {
            "id": int(run["id"]),
            "attempt": int(run.get("run_attempt") or 1),
            "workflow": run["name"],
            "created_at": run["created_at"],
            "updated_at": run.get("updated_at"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
        }
        if "failure_metadata" in run:
            record["failure_metadata"] = run["failure_metadata"]
        if "failed_steps" in run:
            record["failed_steps"] = sanitise_steps(run["failed_steps"])
        public.append(record)
    return public


def _epoch(value) -> str | None:
    if value is None:
        return None
    epoch = float(value)
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat() if epoch else None


def component_observations(
    state: dict, activity: dict | None, automation: dict, now: datetime
) -> list[dict]:
    workflows = {item["name"]: item for item in automation["workflows"]}
    components = [
        {"name": "Public account and joke feed", "observed_at": now.isoformat()},
        {"name": "GitHub workflow metadata", "observed_at": automation["collected_at"]},
        {
            "name": "Joke-request checkpoint",
            "workflow": "bluesky_follows_and_likes",
            "observed_at": _epoch(
                state.get("joke_requests", {}).get("last_checked_at")
            ),
        },
    ]
    for name, workflow, field in (
        (
            "Social action summary",
            "bluesky_follows_and_likes",
            "social_summary_observed",
        ),
        ("Moderation summary", "bluesky_process_reports", "proposals"),
        ("Maintenance review", "bluesky_unfollow", "processed"),
    ):
        measured = [
            run["created_at"]
            for run in (activity or {}).get("runs", [])
            if run.get("workflow") == workflow
            and field in run
            and (field != "social_summary_observed" or run[field] is True)
            and run.get("created_at")
        ]
        components.append(
            {
                "name": name,
                "workflow": workflow,
                "observed_at": max(measured) if measured else None,
            }
        )
    for provider, health in sorted(
        state.get("provider", {}).get("health_checks", {}).items()
    ):
        if health.get("configured") is not False:
            components.append(
                {
                    "name": f"{provider} availability",
                    "workflow": "provider_health_check",
                    "observed_at": _epoch(health.get("last_check_at")),
                }
            )
    for item in components:
        workflow = workflows.get(item.get("workflow"), {})
        interval = workflow.get("expected_interval_hours")
        item["expected_interval_hours"] = interval
        observed = item["observed_at"]
        item["overdue"] = bool(
            observed
            and interval
            and datetime.fromisoformat(observed) < now - timedelta(hours=interval + 2)
        )
        item["last_success_at"] = workflow.get("last_success_at")
    return components
