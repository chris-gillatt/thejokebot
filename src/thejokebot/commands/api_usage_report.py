"""Bounded, incremental API and Actions usage reporting."""

import hashlib
import json
import os
import re
import subprocess
import zipfile
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser

import requests

from thejokebot import api_usage
from thejokebot.commands import dashboard_history, dashboard_workflows
from thejokebot.paths import DASHBOARD_DIR, RESOURCES_DIR, STATE_DIR
from thejokebot.runtime import retry_network_call

CONFIG_FILE = RESOURCES_DIR / "api_limits.json"
CACHE_FILE = STATE_DIR / "api_usage.json"
REPORT_FILE = DASHBOARD_DIR / "data" / "api_usage.json"
API_BASE = "https://api.github.com"
MAX_PAGES = 20
MAX_NEW_ATTEMPTS = 64
DOC_URLS = {
    "bluesky": "https://bsky.network/docs/rate-limits/",
    "github_api": "https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api",
    "github_actions": "https://docs.github.com/en/actions/reference/limits",
    "github_billing": "https://docs.github.com/en/billing/concepts/product-billing/github-actions",
}


def _date(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Usage timestamps must be strings")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Usage timestamps must include a timezone")
    return result


def _integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("Usage counters must be non-negative integers")
    return value


class DocumentText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "svg"}:
            self.ignored += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "svg"} and self.ignored:
            self.ignored -= 1

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def document_hash(content: str) -> str:
    parser = DocumentText()
    parser.feed(content)
    text = " ".join(" ".join(parser.parts).split())
    if len(text) < 100:
        raise ValueError("Limit documentation has no substantial text")
    return hashlib.sha256(text.encode()).hexdigest()


def _request_event(event: dict) -> dict:
    identity = event.get("request")
    if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}", identity):
        raise ValueError("Invalid API request identity")
    service = event.get("service")
    if service not in {"bluesky", "github"}:
        raise ValueError("Invalid API service")
    endpoint = event.get("endpoint")
    if not isinstance(endpoint, str) or not re.fullmatch(r"[a-zA-Z0-9.]+", endpoint):
        raise ValueError("Invalid API endpoint")
    at = event.get("at")
    _date(at)
    points = event.get("write_points_upper_bound")
    if points is not None:
        _integer(points)
    if event.get("group") not in {"pds", "appview", "other_pds", "rest"}:
        raise ValueError("Invalid API quota group")
    if event.get("method") not in {
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "HEAD",
        "OPTIONS",
    }:
        raise ValueError("Invalid HTTP method")
    return {
        "id": identity,
        "source": event["source"],
        "service": service,
        "endpoint": endpoint,
        "at": at,
        "group": event.get("group"),
        "method": event.get("method"),
        "write_points_upper_bound": points,
        "status": None,
        "headers": {},
    }


def _log_event(line: str, run: int, attempt: int) -> dict | None:
    line = re.sub(r"^\d{4}-\d{2}-\d{2}T\S+\s+", "", line)
    if not line.startswith(api_usage.PREFIX):
        return None
    event = json.loads(line[len(api_usage.PREFIX) :])
    if not isinstance(event, dict) or event.get("version") != 1:
        raise ValueError("Unsupported API telemetry")
    if str(event.get("run")) != str(run) or str(event.get("attempt")) != str(attempt):
        raise ValueError("API telemetry does not match its workflow attempt")
    source = event.get("source")
    if not isinstance(source, str) or not re.fullmatch(r"[a-f0-9]{32}", source):
        raise ValueError("Invalid API telemetry source")
    return event


def _merge_response(requests_by_id: dict, event: dict) -> None:
    request = requests_by_id.get(event.get("request"))
    if request is None or request["source"] != event["source"]:
        raise ValueError("Response has no observed request from this source")
    status = event.get("status")
    if status is not None and (type(status) is not int or not 100 <= status <= 599):
        raise ValueError("Invalid observed HTTP status")
    headers = event.get("headers")
    if not isinstance(headers, dict) or not headers.keys() <= set(
        api_usage.RATE_HEADERS
    ):
        raise ValueError("Invalid public rate-limit headers")
    if any(
        not isinstance(value, str) or len(value) > 200 for value in headers.values()
    ):
        raise ValueError("Rate-limit headers must be bounded strings")
    request.update(status=status, headers=headers)


def parse_logs(text: str, run: int, attempt: int) -> tuple[list[dict], str]:
    requests_by_id = {}
    starts = set()
    totals = {}
    source_counts = Counter()
    for line in text.splitlines():
        event = _log_event(line, run, attempt)
        if event is None:
            continue
        source = event["source"]
        kind = event.get("kind")
        if kind == "start":
            starts.add(source)
        elif kind == "request":
            request = _request_event(event)
            if request["id"] not in requests_by_id:
                requests_by_id[request["id"]] = request
                source_counts[source] += 1
        elif kind == "response":
            _merge_response(requests_by_id, event)
        elif kind == "summary":
            totals[source] = _integer(event.get("requests"))
        else:
            raise ValueError("Unknown API telemetry event")
    complete = (
        bool(starts)
        and source_counts.keys() <= starts
        and starts == totals.keys()
        and all(totals[source] == source_counts[source] for source in starts)
    )
    status = (
        "observed"
        if complete
        else "partial"
        if starts or requests_by_id
        else "unavailable"
    )
    return list(requests_by_id.values()), status


def peak_usage(events: list[tuple[datetime, int]], seconds: int) -> int:
    ordered = sorted(events)
    left = used = peak = 0
    for at, weight in ordered:
        used += weight
        while ordered[left][0] <= at - timedelta(seconds=seconds):
            used -= ordered[left][1]
            left += 1
        peak = max(peak, used)
    return peak


def job_seconds(jobs: Sequence[object]) -> int | None:
    total = 0
    for job in jobs:
        if not isinstance(job, dict):
            raise ValueError("Invalid job usage metadata")
        if not job.get("started_at") or not job.get("completed_at"):
            return None
        elapsed = (
            _date(job["completed_at"]) - _date(job["started_at"])
        ).total_seconds()
        if elapsed < 0:
            raise ValueError("Job completed before it started")
        total += int(elapsed)
    return total


def compact_requests(rows: list[dict]) -> list[dict]:
    buckets = {}
    for row in sorted(rows, key=lambda item: _date(item["at"])):
        minute = (
            _date(row["at"])
            .astimezone(UTC)
            .replace(second=0, microsecond=0)
            .isoformat()
        )
        identity = (
            minute,
            row["service"],
            row["group"],
            row["endpoint"],
            row["method"],
        )
        if identity not in buckets:
            buckets[identity] = {
                **row,
                "at": minute,
                "calls": 0,
                "http_429": 0,
                "write_points_upper_bound": 0,
            }
        bucket = buckets[identity]
        bucket["calls"] += 1
        bucket["http_429"] += row["status"] == 429
        points = row["write_points_upper_bound"]
        if bucket["write_points_upper_bound"] is not None:
            bucket["write_points_upper_bound"] = (
                bucket["write_points_upper_bound"] + points
                if points is not None
                else None
            )
        bucket.update(headers=row["headers"], status=row["status"], last_at=row["at"])
    return list(buckets.values())


def _json_get(session, repository: str, path: str, headers: dict, params=None) -> dict:
    def request():
        response = session.get(
            f"{API_BASE}/repos/{repository}/{path}",
            headers=headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Invalid GitHub usage response")
        return payload

    return retry_network_call(request, description="collecting API usage metadata")


def inventory(
    session, repository: str, headers: dict, now: datetime
) -> tuple[list[dict], bool]:
    runs = []
    for page in range(1, MAX_PAGES + 1):
        payload = _json_get(
            session,
            repository,
            "actions/runs",
            headers,
            {
                "created": f">={(now - timedelta(days=30)).isoformat()}",
                "per_page": 100,
                "page": page,
            },
        )
        rows = payload.get("workflow_runs")
        if not isinstance(rows, list):
            raise ValueError("GitHub usage inventory has no workflow_runs")
        runs.extend(rows)
        if len(rows) < 100:
            complete = len(runs) >= _integer(payload.get("total_count"))
            if not complete:
                print(
                    "Warning: GitHub capped the matched run inventory; totals are incomplete."
                )
            return runs, complete
    print("Warning: API usage inventory hit its page limit; totals are incomplete.")
    return runs, False


def _jobs(
    session, repository: str, run: int, attempt: int, headers: dict
) -> list[dict]:
    jobs = []
    for page in range(1, 11):
        payload = _json_get(
            session,
            repository,
            f"actions/runs/{run}/attempts/{attempt}/jobs",
            headers,
            {"per_page": 100, "page": page},
        )
        rows = payload.get("jobs")
        if not isinstance(rows, list):
            raise ValueError("GitHub usage response has no jobs")
        jobs.extend(rows)
        if len(rows) < 100:
            return jobs
    raise RuntimeError("Usage job pagination exceeded its safety limit")


def _attempt(
    session,
    repository: str,
    run: dict,
    attempt: int,
    token: str,
    headers: dict,
    now: datetime,
) -> dict:
    result = {
        "id": _integer(run["id"]),
        "attempt": attempt,
        "workflow": run["name"],
        "created_at": run["created_at"],
        "job_seconds": None,
        "job_status": "unavailable",
        "requests": [],
        "telemetry": "unavailable",
        "checked_at": now.isoformat(),
    }
    try:
        jobs = _jobs(session, repository, run["id"], attempt, headers)
        result["job_seconds"] = job_seconds(jobs)
        result["job_status"] = (
            "observed" if result["job_seconds"] is not None else "partial"
        )
        if jobs:
            result["created_at"] = min(
                (job["started_at"] for job in jobs if job.get("started_at")),
                default=run["created_at"],
            )
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        print(
            f"Warning: job usage unavailable for run {run['id']}/{attempt}: {type(exc).__name__}"
        )
    try:
        logs = dashboard_workflows.fetch_workflow_run_logs(
            session, repository, run["id"], token, attempt=attempt
        )
        observed, result["telemetry"] = parse_logs(logs, run["id"], attempt)
        result["requests"] = compact_requests(observed)
        if result["telemetry"] == "unavailable":
            result["telemetry"] = "not_instrumented"
    except (requests.RequestException, OSError, ValueError, zipfile.BadZipFile) as exc:
        print(
            f"Warning: API telemetry unavailable for run {run['id']}/{attempt}: {type(exc).__name__}"
        )
    return result


def collect_attempts(
    session,
    repository: str,
    token: str,
    headers: dict,
    runs: list[dict],
    cached: list[dict],
    now: datetime,
) -> list[dict]:
    cutoff = now - timedelta(days=30)
    records = {
        (row["id"], row["attempt"]): row
        for row in cached
        if _date(row["created_at"]) >= cutoff
    }
    pending = []
    for run in runs:
        if run.get("status") != "completed":
            continue
        for attempt in reversed(range(1, _integer(run.get("run_attempt", 1)) + 1)):
            previous = records.get((run["id"], attempt))
            retry = (
                previous
                and (
                    previous["telemetry"] in {"unavailable", "partial"}
                    or previous["job_status"] != "observed"
                )
                and now - _date(previous["checked_at"]) >= timedelta(days=1)
            )
            if previous is None or retry:
                pending.append((run, attempt))
    for run, attempt in pending[:MAX_NEW_ATTEMPTS]:
        records[(run["id"], attempt)] = _attempt(
            session, repository, run, attempt, token, headers, now
        )
    return list(records.values())


def _document(session, key: str, expected: str, now: datetime) -> dict:
    def request():
        with session.get(DOC_URLS[key], timeout=30, stream=True) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_content(65536):
                content.extend(chunk)
                if len(content) > 2 * 1024 * 1024:
                    raise ValueError("Limit documentation exceeded its size limit")
            return document_hash(content.decode("utf-8"))

    result = {"id": key, "checked_at": now.isoformat(), "status": "unavailable"}
    try:
        observed = retry_network_call(request, description=f"checking {key} limits")
        result.update(
            sha256=observed, status="unchanged" if observed == expected else "changed"
        )
    except (requests.RequestException, ValueError) as exc:
        print(f"Warning: {key} limit documentation unavailable: {type(exc).__name__}")
    return result


def check_documents(session, config: dict, previous: dict, now: datetime) -> dict:
    results = {}
    for key, expected in config["documents"].items():
        old = previous.get(key)
        if old and now - _date(old["checked_at"]) < timedelta(days=1):
            results[key] = dict(old)
            if "sha256" in old:
                results[key]["status"] = (
                    "unchanged" if old["sha256"] == expected else "changed"
                )
        else:
            results[key] = _document(session, key, expected, now)
    return results


def _quota_report(rows: list[dict], config: dict, documents: dict) -> list[dict]:
    quotas = []
    for limit in config["limits"]:
        samples = []
        for row in rows:
            if row["group"] != "pds":
                continue
            matches = limit["measure"] != "logins" or (
                row["endpoint"] == "com.atproto.server.createSession"
                and row["method"] == "POST"
            )
            if matches:
                weight = (
                    row["write_points_upper_bound"]
                    if limit["measure"] == "write_points"
                    else row.get("calls", 1)
                )
                if weight is not None:
                    samples.append((_date(row["at"]), weight))
        uncertain = limit["measure"] == "write_points" and any(
            row["group"] == "pds" and row["write_points_upper_bound"] is None
            for row in rows
        )
        used = (
            peak_usage(samples, limit["seconds"] + 60)
            if samples and not uncertain
            else None
        )
        quotas.append(
            {
                **limit,
                "observed_peak": used,
                "limit_status": documents.get("bluesky", {}).get(
                    "status", "unavailable"
                ),
                "warning": used is not None
                and used * 100 >= limit["limit"] * config["warning_percent"],
            }
        )
    return quotas


def _period_report(
    runs: list[dict], records: list[dict], rows: list[dict], now: datetime
) -> dict:
    periods = {}
    for days in (1, 7, 30):
        cutoff = now.replace(second=0, microsecond=0) - timedelta(days=days)
        selected = [row for row in records if _date(row["created_at"]) >= cutoff]
        events = [row for row in rows if _date(row["at"]) >= cutoff]
        observed = any(row["telemetry"] in {"observed", "partial"} for row in selected)
        measured_jobs = [
            row["job_seconds"] for row in selected if row["job_seconds"] is not None
        ]
        periods[str(days)] = {
            "workflow_runs": len(
                {run["id"] for run in runs if _date(run["created_at"]) >= cutoff}
            ),
            "attempts": len(selected),
            "attempts_with_job_time": sum(
                row["job_seconds"] is not None for row in selected
            ),
            "observed_job_minutes": round(sum(measured_jobs) / 60, 2)
            if measured_jobs
            else None,
            "attempts_with_telemetry": sum(
                row["telemetry"] == "observed" for row in selected
            ),
            "bluesky_requests": sum(
                row.get("calls", 1) for row in events if row["service"] == "bluesky"
            )
            if observed
            else None,
            "github_requests": sum(
                row.get("calls", 1) for row in events if row["service"] == "github"
            )
            if observed
            else None,
            "http_429": sum(
                row.get("http_429", int(row["status"] == 429)) for row in events
            )
            if observed
            else None,
        }
    return periods


def github_quota(rows: list[dict], now: datetime, warning_percent: int) -> dict | None:
    candidates = [
        row
        for row in rows
        if row["service"] == "github" and "x-ratelimit-limit" in row["headers"]
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda row: _date(row.get("last_at", row["at"])))
    headers = latest["headers"]
    try:
        limit = int(headers["x-ratelimit-limit"])
        remaining = int(headers["x-ratelimit-remaining"])
        reset = datetime.fromtimestamp(int(headers["x-ratelimit-reset"]), UTC)
        if limit <= 0 or not 0 <= remaining <= limit:
            raise ValueError("Invalid quota values")
    except KeyError, TypeError, ValueError, OverflowError:
        print("Warning: GitHub quota headers are incomplete or invalid.")
        return None
    return {
        "limit": limit,
        "remaining": remaining,
        "reset_at": reset.isoformat(),
        "observed_at": latest.get("last_at", latest["at"]),
        "resource": headers.get("x-ratelimit-resource", "unknown"),
        "expired": reset <= now,
        "warning": reset > now and (limit - remaining) * 100 >= limit * warning_percent,
    }


def build_report(
    runs: list[dict],
    records: list[dict],
    documents: dict,
    config: dict,
    now: datetime,
    *,
    complete=True,
    current_requests=None,
) -> dict:
    requests_observed = {
        row["id"]: row for record in records for row in record["requests"]
    }
    rows = list(requests_observed.values())
    quotas = _quota_report(rows, config, documents)
    periods = _period_report(runs, records, rows, now)
    quota = github_quota(
        [*rows, *(current_requests or [])], now, config["warning_percent"]
    )
    warnings = [limit["label"] for limit in quotas if limit["warning"]]
    if quota and quota["warning"]:
        warnings.append("GitHub API quota near its limit")
    warnings.extend(
        f"{key} limit documentation {value['status']}"
        for key, value in documents.items()
        if value["status"] != "unchanged"
    )
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "warning_percent": config["warning_percent"],
        "inventory_complete": complete,
        "periods": periods,
        "quotas": quotas,
        "documents": documents,
        "warnings": warnings,
        "github_quota": quota,
        "coverage": {
            "cached_attempts": len(records),
            "inventory_runs": len(runs),
            "telemetry_observed": sum(
                row["telemetry"] == "observed" for row in records
            ),
        },
        "scope": "Observed shared Python-client HTTP attempts only; gh CLI, third-party Actions, other clients and shared-IP activity are not counted. Server quota headers include usage outside these observations. UTC minute-bucket window estimates include an extra minute to avoid understating rolling peaks. Write points are conservative attempted-operation estimates. Public AppView has no published numeric quota. Job time excludes queue time and is not billed usage; public standard-runner compute is free, but larger runners and storage may be charged.",
    }


def _load(path) -> dict:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError(f"Unsupported API usage state in {path.name}")
    return payload


def public_report() -> dict:
    report = _load(REPORT_FILE)
    if not report:
        print("Warning: API usage report has not been collected yet.")
    return report


def validate_config(config: object) -> dict:
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise ValueError("Unsupported API limit policy")
    warning = _integer(config.get("warning_percent"))
    if not 0 < warning <= 100:
        raise ValueError("API warning percentage must be between 1 and 100")
    documents = config.get("documents")
    if not isinstance(documents, dict) or documents.keys() != DOC_URLS.keys():
        raise ValueError("Limit documentation must use the approved sources")
    if any(
        not isinstance(value, str)
        or not re.fullmatch(r"[a-f0-9]{64}", value)
        or value == "0" * 64
        for value in documents.values()
    ):
        raise ValueError("Limit documentation needs verified SHA-256 fingerprints")
    limits = config.get("limits")
    if not isinstance(limits, list) or not limits:
        raise ValueError("Published API limits must be a non-empty list")
    for limit in limits:
        _validate_limit(limit)
    return config


def _validate_limit(limit: object) -> None:
    if not isinstance(limit, dict):
        raise ValueError("Published API limits must be objects")
    if limit.get("measure") not in {"requests", "logins", "write_points"}:
        raise ValueError("Unsupported published quota measure")
    if not isinstance(limit.get("label"), str) or not limit["label"].strip():
        raise ValueError("Published API limits need a label")
    if _integer(limit.get("seconds")) == 0 or _integer(limit.get("limit")) == 0:
        raise ValueError("Published quotas and windows must be positive")


def main() -> None:
    now = datetime.now(UTC)
    config = validate_config(json.loads(CONFIG_FILE.read_text()))
    cache = _load(CACHE_FILE)
    repository = os.getenv("GITHUB_REPOSITORY", "chris-gillatt/thejokebot")
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+", repository):
        raise ValueError("Invalid repository for API usage reporting")
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        token = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=True
        ).stdout.strip()
    if not token:
        raise ValueError("GitHub authentication is required to read workflow logs")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
        "Authorization": f"Bearer {token}",
    }
    with api_usage.session() as session:
        runs, complete = inventory(session, repository, headers, now)
        records = collect_attempts(
            session, repository, token, headers, runs, cache.get("runs", []), now
        )
        documents = check_documents(session, config, cache.get("documents", {}), now)
    recorder = api_usage.get_recorder()
    current = (
        parse_logs(
            "\n".join(
                api_usage.PREFIX + json.dumps(event) for event in recorder.events
            ),
            int(os.environ["GITHUB_RUN_ID"]),
            int(os.getenv("GITHUB_RUN_ATTEMPT", "1")),
        )[0]
        if recorder
        and os.getenv("GITHUB_ACTIONS") == "true"
        and os.getenv("GITHUB_RUN_ID")
        else []
    )
    report = build_report(
        runs,
        records,
        documents,
        config,
        now,
        complete=complete,
        current_requests=current,
    )
    dashboard_history._write_json(
        CACHE_FILE, {"schema_version": 1, "runs": records, "documents": documents}
    )
    dashboard_history._write_json(REPORT_FILE, report)
    print(
        f"API usage report collected: {len(runs)} runs, {len(records)} cached attempts."
    )


if __name__ == "__main__":
    main()
