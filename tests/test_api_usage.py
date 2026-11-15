import json
import io
import zipfile
import subprocess
import sys
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
import requests
from requests.adapters import HTTPAdapter
from requests.structures import CaseInsensitiveDict
from atproto_client.exceptions import NetworkError, RateLimitExceededError
from atproto_client.request import Request

from thejokebot import api_usage
from thejokebot.commands import api_usage_report as report

NOW = datetime(2026, 11, 15, 5, 30, tzinfo=UTC)


def test_interpreter_exit_does_not_publish_opted_out_synthetic_traffic():
    script = (
        "import io, os\n"
        "from contextlib import redirect_stdout\n"
        "from thejokebot import api_usage\n"
        "os.environ['THEJOKEBOT_API_USAGE_ENABLED'] = 'true'\n"
        "os.environ.pop('GITHUB_RUN_ID', None)\n"
        "with redirect_stdout(io.StringIO()):\n"
        "    api_usage.get_recorder()\n"
        "os.environ['THEJOKEBOT_API_USAGE_ENABLED'] = 'false'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert result.stdout == ""
    assert report.parse_logs(result.stdout, 42, 1) == ([], "unavailable")


def observed_events(monkeypatch, attempt=1):
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", str(attempt))
    monkeypatch.setattr(api_usage, "_now", lambda: NOW.isoformat())
    events = []
    recorder = api_usage.Recorder(emit=events.append)
    identity = recorder.begin(
        "POST", "https://bsky.social/xrpc/com.atproto.repo.createRecord", native=True
    )
    recorder.finish(identity, 429, {})
    recorder.begin(
        "GET", "https://bsky.social/xrpc/app.bsky.actor.getProfile", native=True
    )
    recorder.summary()
    return events


def log_text(events):
    return "\n".join(
        NOW.isoformat() + " " + api_usage.PREFIX + json.dumps(event) for event in events
    )


def test_native_attempts_include_clones_failures_and_rate_limits_without_credentials(
    monkeypatch,
):
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    events = []
    recorder = api_usage.Recorder(emit=events.append)

    def respond(request):
        if request.url.path.endswith("resolveHandle"):
            raise httpx.ConnectError("private exception detail", request=request)
        status = 429 if request.url.path.endswith("createSession") else 200
        return httpx.Response(
            status,
            json={"error": "RateLimitExceeded"} if status == 429 else {},
            headers={"ratelimit-limit": "3000", "Authorization": "private-token"},
        )

    request = Request(
        transport=httpx.MockTransport(respond),
        event_hooks={
            "request": [recorder.native_request],
            "response": [recorder.native_response],
        },
    )
    clone = request.clone()
    try:
        request.post(
            "https://bsky.social/xrpc/com.atproto.repo.applyWrites",
            json={
                "repo": "private-account",
                "writes": [
                    {
                        "$type": "com.atproto.repo.applyWrites#create",
                        "value": "private-record",
                    },
                    {"$type": "com.atproto.repo.applyWrites#delete"},
                ],
            },
        )
        with pytest.raises(RateLimitExceededError):
            clone.post(
                "https://bsky.social/xrpc/com.atproto.server.createSession",
                json={"identifier": "private-user", "password": "private-password"},
            )
        with pytest.raises(NetworkError):
            clone.get(
                "https://bsky.social/xrpc/com.atproto.identity.resolveHandle?handle=private-handle"
            )
        recorder.summary()
    finally:
        clone.close()
        request.close()
    attempts = [event for event in events if event["kind"] == "request"]
    responses = [event for event in events if event["kind"] == "response"]
    assert len(attempts) == 3
    assert attempts[0]["write_points_upper_bound"] == 4
    assert len(responses) == 2
    assert responses[1]["status"] == 429
    assert responses[0]["headers"] == {"ratelimit-limit": "3000"}
    assert events[-1]["requests"] == 3
    assert "private" not in json.dumps(events)


def test_requests_adapter_preserves_errors_and_counts_each_retry(monkeypatch):
    events = []
    recorder = api_usage.Recorder(emit=events.append)
    monkeypatch.setattr(api_usage, "get_recorder", lambda: recorder)
    prepared = requests.Request(
        "GET", "https://api.github.com/repos/private/actions/runs?token=private-token"
    ).prepare()
    adapter = api_usage.UsageAdapter()
    response = requests.Response()
    response.status_code = 200
    response.headers = CaseInsensitiveDict(
        {
            "X-RateLimit-Remaining": "900",
            "Authorization": "private-token",
        }
    )
    calls = []

    def send(self, request, **kwargs):
        calls.append(request)
        if len(calls) == 1:
            raise requests.ConnectionError("private failure")
        return response

    monkeypatch.setattr(HTTPAdapter, "send", send)
    with pytest.raises(requests.ConnectionError):
        adapter.send(prepared)
    assert adapter.send(prepared) is response
    assert recorder.requests == 2
    assert "private" not in json.dumps(events)
    assert events[-1]["headers"] == {"x-ratelimit-remaining": "900"}


@pytest.mark.parametrize("content", [b"not JSON", b'{"writes":[{"$type":5}]}'])
def test_unknown_batch_points_do_not_change_request_execution(content, capsys):
    events = []
    recorder = api_usage.Recorder(emit=events.append)
    assert recorder.begin(
        "POST",
        "https://bsky.social/xrpc/com.atproto.repo.applyWrites",
        native=True,
        content=content,
    )
    assert events[-1]["write_points_upper_bound"] is None
    assert "estimate unavailable" in capsys.readouterr().err


def test_producer_to_collector_deduplicates_logs_and_preserves_unknown_outcomes(
    monkeypatch,
):
    events = observed_events(monkeypatch)
    rows, status = report.parse_logs(log_text(events + events), 42, 1)
    assert status == "observed"
    assert len(rows) == 2
    assert rows[0]["status"] == 429
    assert rows[1]["status"] is None
    compact = report.compact_requests(rows + [{**rows[0], "id": "b" * 32}])
    assert sum(row["calls"] for row in compact) == 3
    assert sum(row["http_429"] for row in compact) == 2
    assert sum(row["write_points_upper_bound"] for row in compact) == 6
    partial, status = report.parse_logs(log_text(events[:-1]), 42, 1)
    assert len(partial) == 2
    assert status == "partial"
    assert report.parse_logs("unrelated logs", 42, 1) == ([], "unavailable")


@pytest.mark.parametrize(
    "mutation",
    [
        "run",
        "version",
        "source",
        "request-id",
        "endpoint",
        "timestamp",
        "points",
        "group",
        "method",
        "response-id",
        "status",
        "headers",
        "summary",
        "kind",
    ],
)
def test_bad_telemetry_fails_explicitly_without_success_shaped_counts(
    monkeypatch, mutation
):
    events = observed_events(monkeypatch)
    if mutation in ("run", "version", "source"):
        events[0][mutation] = "invalid"
    elif mutation in (
        "request-id",
        "endpoint",
        "timestamp",
        "points",
        "group",
        "method",
    ):
        key = {
            "request-id": "request",
            "timestamp": "at",
            "points": "write_points_upper_bound",
        }.get(mutation, mutation)
        events[1][key] = False
    elif mutation in ("response-id", "status", "headers"):
        key = {"response-id": "request"}.get(mutation, mutation)
        events[2][key] = (
            {"Authorization": "private"} if mutation == "headers" else False
        )
    elif mutation == "summary":
        events[-1]["requests"] = True
    else:
        events[0]["kind"] = "unexpected"
    with pytest.raises(ValueError):
        report.parse_logs(log_text(events), 42, 1)


@pytest.mark.parametrize("calls,warning", [(2399, False), (2400, True)])
def test_warning_starts_at_exactly_eighty_percent_without_changing_actions(
    monkeypatch, calls, warning
):
    rows, _ = report.parse_logs(log_text(observed_events(monkeypatch)), 42, 1)
    row = {**rows[1], "calls": calls, "http_429": 0}
    config = {
        "warning_percent": 80,
        "limits": [
            {
                "label": "PDS requests",
                "measure": "requests",
                "seconds": 300,
                "limit": 3000,
            },
        ],
    }
    record = {
        "id": 42,
        "attempt": 1,
        "created_at": NOW.isoformat(),
        "job_seconds": None,
        "requests": [row],
        "telemetry": "observed",
    }
    result = report.build_report([], [record], {}, config, NOW)
    assert result["quotas"][0]["observed_peak"] == calls
    assert result["quotas"][0]["warning"] is warning
    assert result["periods"]["7"]["bluesky_requests"] == calls
    assert result["periods"]["30"]["observed_job_minutes"] is None
    empty = report.build_report([], [], {}, config, NOW)
    assert empty["quotas"][0]["observed_peak"] is None
    assert empty["periods"]["7"]["bluesky_requests"] is None


def test_job_time_excludes_queue_and_sums_parallel_jobs():
    jobs = [
        {
            "started_at": NOW.isoformat(),
            "completed_at": (NOW + timedelta(minutes=2)).isoformat(),
        }
    ] * 2
    assert report.job_seconds(jobs) == 240
    assert report.job_seconds([]) == 0
    assert report.job_seconds([{"started_at": NOW.isoformat()}]) is None
    with pytest.raises(ValueError):
        report.job_seconds(
            [
                {
                    "started_at": NOW.isoformat(),
                    "completed_at": (NOW - timedelta(seconds=1)).isoformat(),
                }
            ]
        )
    with pytest.raises(ValueError):
        report.job_seconds([None])
    assert report.peak_usage([(NOW, 10), (NOW + timedelta(seconds=300), 20)], 300) == 20


def test_server_quota_uses_authoritative_remaining_and_expires(monkeypatch, capsys):
    rows, _ = report.parse_logs(log_text(observed_events(monkeypatch)), 42, 1)
    row = {
        **rows[0],
        "service": "github",
        "headers": {
            "x-ratelimit-limit": "1000",
            "x-ratelimit-remaining": "200",
            "x-ratelimit-reset": str(int((NOW + timedelta(hours=1)).timestamp())),
            "x-ratelimit-resource": "core",
        },
    }
    current = report.github_quota([row], NOW, 80)
    expired = report.github_quota([row], NOW + timedelta(hours=2), 80)
    assert current is not None and current["warning"] is True
    assert expired is not None and expired["warning"] is False
    row["headers"]["x-ratelimit-limit"] = "invalid"
    assert report.github_quota([row], NOW, 80) is None
    assert "incomplete or invalid" in capsys.readouterr().out


def test_reporter_persists_reruns_and_document_changes_without_leaking_auth(
    monkeypatch, tmp_path
):
    body = "<main>" + "Published limits and usage " * 20 + "</main>"
    config = json.loads(report.CONFIG_FILE.read_text())
    config["documents"] = {key: report.document_hash(body) for key in report.DOC_URLS}
    config_file = tmp_path / "limits.json"
    config_file.write_text(json.dumps(config))
    monkeypatch.setattr(report, "CONFIG_FILE", config_file)
    monkeypatch.setattr(report, "CACHE_FILE", tmp_path / "cache.json")
    monkeypatch.setattr(report, "REPORT_FILE", tmp_path / "report.json")
    monkeypatch.setenv("GITHUB_TOKEN", "private-token")
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    source_events = {
        attempt: observed_events(monkeypatch, attempt) for attempt in (1, 2)
    }
    monkeypatch.delenv("GITHUB_RUN_ID")
    run = {
        "id": 42,
        "name": "future-workflow",
        "status": "completed",
        "created_at": NOW.isoformat(),
        "run_attempt": 2,
    }
    fetched = []

    class Response:
        def __init__(self, payload=None, content=b""):
            self.payload = payload
            self.content = content

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

        def iter_content(self, size):
            yield body.encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class Session:
        def get(self, url, **kwargs):
            fetched.append(url)
            return report_response(url, kwargs, source_events, run, Response)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(report.api_usage, "session", Session)
    report.main()
    public = report.public_report()
    assert public["periods"]["30"]["workflow_runs"] == 1
    assert public["periods"]["30"]["attempts"] == 2
    assert public["periods"]["30"]["observed_job_minutes"] == 2
    assert public["periods"]["7"]["bluesky_requests"] == 4
    assert public["periods"]["7"]["http_429"] == 2
    assert all(row["status"] == "unchanged" for row in public["documents"].values())
    assert (
        "private-token"
        not in report.CACHE_FILE.read_text() + report.REPORT_FILE.read_text()
    )
    fetched.clear()
    report.main()
    assert len(fetched) == 1
    changed = report._document(Session(), "bluesky", "different", NOW)
    assert changed["status"] == "changed"


def report_response(url, kwargs, source_events, run, response):
    if url in report.DOC_URLS.values():
        assert "Authorization" not in kwargs.get("headers", {})
        return response()
    assert kwargs["headers"]["Authorization"] == "Bearer private-token"
    if url.endswith("actions/runs"):
        return response({"workflow_runs": [run], "total_count": 1})
    if url.endswith("/jobs"):
        return response(
            {
                "jobs": [
                    {
                        "started_at": NOW.isoformat(),
                        "completed_at": (NOW + timedelta(minutes=1)).isoformat(),
                    }
                ]
            }
        )
    attempt = int(url.split("/attempts/")[1].split("/")[0])
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("job.txt", log_text(source_events[attempt]))
    return response(content=archive.getvalue())


def test_conservative_minute_windows_and_unknown_write_batches(monkeypatch):
    rows, _ = report.parse_logs(log_text(observed_events(monkeypatch)), 42, 1)
    first = {**rows[1], "at": (NOW + timedelta(seconds=59)).isoformat(), "calls": 15}
    second = {**first, "id": "c" * 32, "at": (NOW + timedelta(minutes=5)).isoformat()}
    buckets = report.compact_requests([first, second])
    # Raw requests really overlap this five-minute window despite minute rounding.
    for bucket in buckets:
        bucket["calls"] = 15
    config = {
        "warning_percent": 80,
        "limits": [
            {"label": "requests", "measure": "requests", "seconds": 300, "limit": 30},
            {
                "label": "writes",
                "measure": "write_points",
                "seconds": 3600,
                "limit": 5000,
            },
        ],
    }
    assert report._quota_report(buckets, config, {})[0]["observed_peak"] == 30
    unknown = report.compact_requests([{**rows[0], "write_points_upper_bound": None}])
    assert report._quota_report(unknown, config, {})[1]["observed_peak"] is None
    offset = {**rows[0], "at": "2026-11-15T06:30:10+01:00", "id": "d" * 32}
    merged = report.compact_requests([offset, rows[0]])
    assert len(merged) == 1
    assert merged[0]["calls"] == 2
    assert merged[0]["last_at"] == offset["at"]


def test_incremental_backfill_cap_and_transient_retry_age(monkeypatch):
    runs = [
        {
            "id": identity,
            "name": "workflow",
            "status": "completed",
            "created_at": NOW.isoformat(),
            "run_attempt": 1,
        }
        for identity in range(5, 0, -1)
    ]
    recent = {
        "id": 1,
        "attempt": 1,
        "created_at": NOW.isoformat(),
        "checked_at": NOW.isoformat(),
        "telemetry": "unavailable",
        "job_status": "unavailable",
    }
    fetched = []

    def attempt(session, repository, run, number, token, headers, now):
        fetched.append(run["id"])
        return {
            **recent,
            "id": run["id"],
            "telemetry": "observed",
            "job_status": "observed",
        }

    monkeypatch.setattr(report, "_attempt", attempt)
    monkeypatch.setattr(report, "MAX_NEW_ATTEMPTS", 2)
    records = report.collect_attempts(None, "owner/repo", "", {}, runs, [recent], NOW)
    assert fetched == [5, 4]
    records = report.collect_attempts(
        None, "owner/repo", "", {}, runs, records, NOW + timedelta(days=2)
    )
    assert fetched == [5, 4, 3, 2]
    report.collect_attempts(
        None, "owner/repo", "", {}, runs, records, NOW + timedelta(days=2)
    )
    assert fetched == [5, 4, 3, 2, 1]


def test_inventory_and_job_pagination_are_bounded_and_invalid_metadata_fails(
    monkeypatch, capsys
):
    fetched = []

    def get(session, repository, path, headers, params):
        fetched.append(params["page"])
        return {
            "workflow_runs": [{"id": params["page"] * 100 + n} for n in range(100)],
            "jobs": [{}] * 100,
            "total_count": 201,
        }

    monkeypatch.setattr(report, "_json_get", get)
    monkeypatch.setattr(report, "MAX_PAGES", 2)
    runs, complete = report.inventory(None, "owner/repo", {}, NOW)
    assert len(runs) == 200 and complete is False
    assert fetched == [1, 2]
    assert "incomplete" in capsys.readouterr().out
    fetched.clear()
    with pytest.raises(RuntimeError, match="safety limit"):
        report._jobs(None, "owner/repo", 42, 1, {})
    assert fetched == list(range(1, 11))
    monkeypatch.setattr(report, "_json_get", lambda *args: {})
    with pytest.raises(ValueError, match="workflow_runs"):
        report.inventory(None, "owner/repo", {}, NOW)
    with pytest.raises(ValueError, match="no jobs"):
        report._jobs(None, "owner/repo", 42, 1, {})


def test_github_filtered_search_truncation_does_not_claim_complete_inventory(
    monkeypatch, capsys
):
    def get(session, repository, path, headers, params):
        return {
            "total_count": 1009 if params["page"] <= 10 else 0,
            "workflow_runs": [{"id": n} for n in range(100)]
            if params["page"] <= 10
            else [],
        }

    monkeypatch.setattr(report, "_json_get", get)
    runs, complete = report.inventory(None, "owner/repo", {}, NOW)
    assert len(runs) == 100
    assert complete is False
    assert "incomplete" in capsys.readouterr().out


def test_inventory_splits_capped_window_and_deduplicates_boundary_runs(monkeypatch):
    calls = []
    midpoint = NOW - timedelta(days=15)

    def get(session, repository, path, headers, params):
        calls.append(params)
        if len(calls) == 1:
            return {"total_count": 3, "workflow_runs": [{"id": 1}]}
        start, end = params["created"].split("..")
        if start == midpoint.isoformat():
            return {"total_count": 2, "workflow_runs": [{"id": 1}, {"id": 2}]}
        assert end == midpoint.isoformat()
        return {"total_count": 2, "workflow_runs": [{"id": 2}, {"id": 3}]}

    monkeypatch.setattr(report, "_json_get", get)
    monkeypatch.setattr(report, "FILTERED_RUN_LIMIT", 2)
    rows, complete = report.inventory(None, "owner/repo", {}, NOW)
    assert complete and {row["id"] for row in rows} == {1, 2, 3}
    assert len(calls) == 3
    assert report._split_inventory_window(NOW, NOW) == []
    assert report._split_inventory_window(NOW, NOW + timedelta(microseconds=1)) == []


def test_partitioned_inventory_retains_newest_first_backfill_order(monkeypatch):
    payloads = iter(
        [
            {
                "total_count": 3,
                "workflow_runs": [{"id": 1, "created_at": "2026-11-01T00:00:00Z"}],
            },
            {
                "total_count": 2,
                "workflow_runs": [
                    {"id": 1, "created_at": "2026-11-01T00:00:00Z"},
                    {"id": 2, "created_at": "2026-11-15T00:00:00Z"},
                ],
            },
            {
                "total_count": 1,
                "workflow_runs": [{"id": 3, "created_at": "2026-11-10T00:00:00Z"}],
            },
        ]
    )
    monkeypatch.setattr(report, "_json_get", lambda *a: next(payloads))
    monkeypatch.setattr(report, "FILTERED_RUN_LIMIT", 2)
    rows, complete = report.inventory(None, "owner/repo", {}, NOW)
    assert complete and [row["id"] for row in rows] == [2, 3, 1]
    assert report._period_report(rows, [], [], NOW)["30"]["workflow_runs"] == 3


def test_inventory_full_page_at_exact_count_needs_no_extra_request(monkeypatch):
    def get(*args):
        return {"total_count": 100, "workflow_runs": [{"id": n} for n in range(100)]}

    monkeypatch.setattr(report, "_json_get", get)
    monkeypatch.setattr(report, "MAX_PAGES", 1)
    rows, complete = report.inventory(None, "owner/repo", {}, NOW)
    assert len(rows) == 100 and complete


def test_inventory_short_page_below_matched_total_remains_incomplete(monkeypatch):
    monkeypatch.setattr(
        report,
        "_json_get",
        lambda *a: {"total_count": 10, "workflow_runs": [{"id": 1}]},
    )
    assert report.inventory(None, "owner/repo", {}, NOW)[1] is False


def test_inventory_does_not_forget_parent_total_after_splitting(monkeypatch):
    count = 0

    def get(*args):
        nonlocal count
        count += 1
        return {"total_count": 3 if count == 1 else 1, "workflow_runs": [{"id": 1}]}

    monkeypatch.setattr(report, "_json_get", get)
    monkeypatch.setattr(report, "FILTERED_RUN_LIMIT", 2)
    assert report.inventory(None, "owner/repo", {}, NOW)[1] is False


def test_missing_job_and_log_observations_stay_unavailable(monkeypatch, capsys):
    def unavailable(*args, **kwargs):
        raise requests.ConnectionError("private request details")

    monkeypatch.setattr(report, "_jobs", unavailable)
    monkeypatch.setattr(
        report.dashboard_workflows, "fetch_workflow_run_logs", unavailable
    )
    row = report._attempt(
        None,
        "owner/repo",
        {"id": 42, "name": "workflow", "created_at": NOW.isoformat()},
        1,
        "",
        {},
        NOW,
    )
    assert row["job_seconds"] is None
    assert row["requests"] == []
    assert row["telemetry"] == "unavailable"
    messages = capsys.readouterr().out
    assert (
        "job usage unavailable" in messages and "API telemetry unavailable" in messages
    )
    assert "private request details" not in messages


def test_document_checks_ignore_scripts_and_fail_explicitly_on_oversized_pages(capsys):
    body = "<main>" + "Published quota " * 20 + "</main>"
    assert report.document_hash(
        "<script>dynamic private data</script>" + body
    ) == report.document_hash(body)
    with pytest.raises(ValueError, match="substantial text"):
        report.document_hash("empty")
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        iter_content=lambda size: iter([b"x" * (2 * 1024 * 1024 + 1)]),
    )
    session = SimpleNamespace(get=lambda *args, **kwargs: nullcontext(response))
    result = report._document(session, "bluesky", "expected", NOW)
    assert result["status"] == "unavailable"
    assert "documentation unavailable" in capsys.readouterr().out


def test_reviewed_document_fingerprint_updates_cached_status_without_refetching():
    cached = {
        "bluesky": {
            "sha256": "reviewed",
            "status": "changed",
            "checked_at": NOW.isoformat(),
        }
    }
    result = report.check_documents(
        None, {"documents": {"bluesky": "reviewed"}}, cached, NOW
    )
    assert result["bluesky"]["status"] == "unchanged"
    assert cached["bluesky"]["status"] == "changed"


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "percentage",
        "sources",
        "fingerprint",
        "empty",
        "measure",
        "label",
        "window",
        "limit",
    ],
)
def test_invalid_quota_policy_never_silently_falls_back(mutation):
    config = json.loads(report.CONFIG_FILE.read_text())
    if mutation == "schema":
        config["schema_version"] = 2
    elif mutation == "percentage":
        config["warning_percent"] = True
    elif mutation == "sources":
        config["documents"] = {"unapproved": "a" * 64}
    elif mutation == "fingerprint":
        config["documents"]["bluesky"] = "0" * 64
    elif mutation == "empty":
        config["limits"] = []
    else:
        key = {"window": "seconds"}.get(mutation, mutation)
        config["limits"][0][key] = "" if mutation in {"measure", "label"} else 0
    with pytest.raises(ValueError):
        report.validate_config(config)


def test_cli_quota_observation_is_actions_only_and_auth_fallback_is_private(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    recorder = api_usage.Recorder(emit=lambda event: None)
    identity = recorder.begin(
        "GET", "https://api.github.com/repos/owner/repo/actions/runs"
    )
    recorder.finish(
        identity,
        200,
        {
            "x-ratelimit-limit": "1000",
            "x-ratelimit-remaining": "200",
            "x-ratelimit-reset": str(
                int((datetime.now(UTC) + timedelta(hours=1)).timestamp())
            ),
        },
    )
    monkeypatch.setattr(report.api_usage, "get_recorder", lambda: recorder)
    monkeypatch.setattr(report.api_usage, "session", lambda: nullcontext(None))
    monkeypatch.setattr(
        report.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="private-token"),
    )
    monkeypatch.setattr(report, "inventory", lambda *args: ([], True))
    monkeypatch.setattr(report, "collect_attempts", lambda *args: [])
    monkeypatch.setattr(report, "check_documents", lambda *args: {})
    monkeypatch.setattr(report, "CACHE_FILE", tmp_path / "cache.json")
    monkeypatch.setattr(report, "REPORT_FILE", tmp_path / "public.json")
    report.main()
    assert report.public_report()["github_quota"]["warning"] is True
    assert "private-token" not in report.REPORT_FILE.read_text()
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    report.main()
    assert report.public_report()["github_quota"] is None
    report.REPORT_FILE.write_text('{"schema_version":2}')
    with pytest.raises(ValueError, match="Unsupported API usage"):
        report.public_report()


def test_streamed_native_requests_preserve_body_and_unknown_write_estimate(capsys):
    events = []
    recorder = api_usage.Recorder(emit=events.append)
    content = b'{"writes":[{"$type":"com.atproto.repo.applyWrites#create"}]}'

    def transport(request):
        assert request.read() == content
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(
        transport=httpx.MockTransport(transport),
        event_hooks={
            "request": [recorder.native_request],
            "response": [recorder.native_response],
        },
    ) as client:
        response = client.post(
            "https://bsky.social/xrpc/com.atproto.repo.applyWrites",
            content=iter([content]),
        )
    assert response.json() == {"ok": True}
    assert (
        next(event for event in events if event["kind"] == "request")[
            "write_points_upper_bound"
        ]
        is None
    )
    assert "streamed write-point estimate unavailable" in capsys.readouterr().err


def test_shared_requests_session_records_only_supported_services_and_honours_opt_out(
    monkeypatch, capsys
):
    monkeypatch.setenv("THEJOKEBOT_API_USAGE_ENABLED", "true")
    monkeypatch.setattr(api_usage, "_recorder", None)

    def send(adapter, request, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"ok":true}'
        response.request = request
        return response

    monkeypatch.setattr(HTTPAdapter, "send", send)
    with api_usage.session() as session:
        assert (
            session.get(
                "https://api.github.com/repos/owner/repo?private=value"
            ).status_code
            == 200
        )
        session.get("https://example.org/unobserved")
        api_usage._finish()
        events = [
            json.loads(line[len(api_usage.PREFIX) :])
            for line in capsys.readouterr().out.splitlines()
        ]
        assert [event["service"] for event in events if event["kind"] == "request"] == [
            "github"
        ]
        assert events[-1]["requests"] == 1
        assert "private" not in json.dumps(events)
        monkeypatch.setenv("THEJOKEBOT_API_USAGE_ENABLED", "false")
        session.get("https://api.github.com/repos/owner/repo")
        assert capsys.readouterr().out == ""
    monkeypatch.setenv("THEJOKEBOT_API_USAGE_ENABLED", "invalid")
    with pytest.raises(ValueError, match="must be true or false"):
        api_usage.native_hooks()


def test_dashboard_collector_embeds_public_report_and_surfaces_its_warning(monkeypatch):
    from thejokebot.commands import collect_dashboard_metrics as collector

    public = report.build_report(
        [],
        [],
        {"bluesky": {"status": "changed"}},
        json.loads(report.CONFIG_FILE.read_text()),
        NOW,
    )
    metrics = {
        "account": {"handle": "test.bsky.social"},
        "generated_at": NOW.isoformat(),
        "automation": {"alerts": []},
        "engagement_checkpoints": {},
    }
    saved = []
    monkeypatch.setenv("BLUESKY_USERNAME", "test.bsky.social")
    monkeypatch.setattr(collector.api_usage, "session", lambda: None)
    monkeypatch.setattr(collector, "fetch_workflow_runs", lambda *args: [])
    monkeypatch.setattr(collector, "_load_existing", lambda: {})
    monkeypatch.setattr(collector.bot_state, "load_state", lambda: {})
    monkeypatch.setattr(collector.dashboard_engagement, "load", lambda *args: {})
    monkeypatch.setattr(collector, "collect_workflow_activity", lambda *args: {})
    monkeypatch.setattr(collector, "collect_metrics", lambda *args, **kwargs: metrics)
    monkeypatch.setattr(collector.api_usage_report, "public_report", lambda: public)
    for name in (
        "_load_history_partitions",
        "_migrate_existing_history",
        "_merge_history_partitions",
        "_collector_existing",
        "_history_from_collection",
        "_write_history",
        "_write_json",
    ):
        monkeypatch.setattr(collector.dashboard_history, name, lambda *args: {})
    monkeypatch.setattr(
        collector.dashboard_history, "_compact_metrics", lambda value, now: value
    )
    monkeypatch.setattr(collector, "_write_metrics", saved.append)
    collector.main()
    assert saved[0]["api_usage"] == public
    assert saved[0]["automation"]["alerts"] == [
        {"kind": "api_usage", "level": "attention", "count": 1}
    ]
