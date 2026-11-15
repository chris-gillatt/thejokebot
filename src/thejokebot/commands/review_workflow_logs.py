"""Collect bounded, read-only evidence for the GitHub Actions review skill."""

import json
import re
import subprocess
import zipfile
from datetime import datetime, timedelta, timezone

import requests

from thejokebot.commands.dashboard_workflows import (
    GITHUB_API_BASE,
    _github_headers,
    fetch_workflow_log_files,
)

REPOSITORY = "chris-gillatt/thejokebot"
PAGE_LIMIT = 10
RUN_LIMIT = 20
WINDOW_DAYS = 7
LINE_LIMIT = 80
SIGNAL = re.compile(
    r"warn|deprecat|error|fail|advisory|vulnerab|obsolete|retir|migrat|"
    r"recommend|consider|experimental|unsupported|rate.limit|timed?.out",
    re.IGNORECASE,
)
SENSITIVE = re.compile(
    r"token|secret|password|passwd|authorization|credential|api[_ -]?key|"
    r"bearer|github_pat_|gh[pousr]_|-----BEGIN|[\w.+-]+@[\w.-]+\.[a-z]{2,}",
    re.IGNORECASE,
)
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def safe_text(value: object) -> str:
    """Omit suspicious lines entirely; this is not a guarantee of secret detection."""
    text = ANSI.sub("", str(value))
    if SENSITIVE.search(text):
        return "[omitted: potentially sensitive content]"
    text = re.sub(r"https?://\S+", "[URL omitted]", text)
    return "".join(c for c in text if c.isprintable())[:500]


def select_runs(runs: list[dict]) -> list[dict]:
    """Prefer one recent completed attempt per workflow, then fill by recency."""
    ordered = sorted(runs, key=lambda run: run["created_at"], reverse=True)
    selected, remaining, seen = [], [], set()
    for run in ordered:
        key = run["workflow_id"]
        if key in seen:
            remaining.append(run)
        else:
            selected.append(run)
            seen.add(key)
    return (selected + remaining)[:RUN_LIMIT]


def evidence_files(files: dict[str, str]) -> list[dict]:
    """Retain locations and counts without emitting full raw logs."""
    result = []
    for filename, content in files.items():
        matches = [
            {"line": number, "text": safe_text(line)}
            for number, line in enumerate(content.splitlines(), 1)
            if SIGNAL.search(line)
        ]
        result.append(
            {
                "source_file": safe_text(filename),
                "lines": len(content.splitlines()),
                "signal_lines": len(matches),
                "omitted_signal_lines": max(0, len(matches) - LINE_LIMIT),
                "excerpts": matches[:LINE_LIMIT],
            }
        )
    return result


def _get(session, path, params=None):
    response = session.get(
        f"{GITHUB_API_BASE}/repos/{REPOSITORY}/{path}", params=params, timeout=30
    )
    response.raise_for_status()
    return response.json()


def inventory(session, now: datetime) -> tuple[list[dict], bool, int]:
    cutoff = (now - timedelta(days=WINDOW_DAYS)).isoformat()
    runs = {}
    total = 0
    complete = False
    for page in range(1, PAGE_LIMIT + 1):
        payload = _get(
            session,
            "actions/runs",
            {
                "created": f">={cutoff}",
                "status": "completed",
                "per_page": 100,
                "page": page,
            },
        )
        total = max(total, payload["total_count"])
        for run in payload["workflow_runs"]:
            runs[run["id"]] = run
        if len(payload["workflow_runs"]) < 100:
            complete = len(runs) >= total
            break
    return list(runs.values()), complete, total


def job_sources(session, run: dict) -> dict:
    jobs = []
    complete = False
    for page in range(1, PAGE_LIMIT + 1):
        payload = _get(
            session,
            f"actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs",
            {"per_page": 100, "page": page},
        )
        for job in payload["jobs"]:
            jobs.append(
                {
                    "id": job["id"],
                    "name": safe_text(job["name"]),
                    "url": f"https://github.com/{REPOSITORY}/actions/runs/{run['id']}/job/{job['id']}",
                    "steps": [
                        {"number": step["number"], "name": safe_text(step["name"])}
                        for step in job.get("steps", [])
                    ],
                }
            )
        if len(payload["jobs"]) < 100:
            complete = True
            break
    return {"complete": complete, "jobs": jobs}


def collect(session, token: str, now: datetime) -> dict:
    runs, complete, total = inventory(session, now)
    selected = select_runs(runs)
    report = {
        "repository": REPOSITORY,
        "observed_at": now.isoformat(),
        "window_days": WINDOW_DAYS,
        "inventory_complete": complete,
        "reported_total_runs": total,
        "discovered_runs": len(runs),
        "unselected_discovered_runs": len(runs) - len(selected),
        "limitations": [
            "Latest attempt per discovered run only; earlier rerun attempts are not sampled.",
            "Window uses run creation time; older runs rerun within the window are excluded.",
            "Signal matching is heuristic; absence of excerpts does not establish absence of problems.",
            "Excerpts remain untrusted and require human sensitivity review before publication.",
        ],
        "runs": [],
    }
    for run in selected:
        entry = {
            "id": run["id"],
            "attempt": run["run_attempt"],
            "commit": run["head_sha"],
            "workflow_id": run["workflow_id"],
            "workflow": safe_text(run["name"]),
            "workflow_path": safe_text(run["path"]),
            "created_at": run["created_at"],
            "conclusion": run["conclusion"],
            "url": f"https://github.com/{REPOSITORY}/actions/runs/{run['id']}/attempts/{run['run_attempt']}",
        }
        try:
            entry["sources"] = job_sources(session, run)
        except requests.RequestException, ValueError, KeyError:
            entry["sources"] = {"complete": False, "jobs": []}
        try:
            files = fetch_workflow_log_files(
                session,
                REPOSITORY,
                run["id"],
                token,
                attempt=run["run_attempt"],
                retry_call=lambda call, **kwargs: call(),
            )
            entry["log_status"] = "available" if files else "empty"
            entry["files"] = evidence_files(files)
        except requests.RequestException, ValueError, zipfile.BadZipFile, OSError:
            entry["log_status"] = "unavailable"
            entry["files"] = []
        report["runs"].append(entry)
    return report


def main() -> None:
    """Use gh authentication in memory, without printing credentials or full logs."""
    token = subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    with requests.Session() as session:
        session.headers.update(_github_headers(token))
        report = collect(session, token, datetime.now(timezone.utc))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
