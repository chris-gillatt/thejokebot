"""Evidence fidelity, bounded sampling and safe failure tests for log review."""

import io
import json
import zipfile
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
import requests

from thejokebot.commands import review_workflow_logs as review
from thejokebot.commands import dashboard_workflows as workflows

NOW = datetime(2026, 11, 15, tzinfo=timezone.utc)


def run(number=1, workflow=1):
    return {
        "id": number,
        "workflow_id": workflow,
        "run_attempt": 2,
        "created_at": f"2026-11-15T00:00:{number:02d}Z",
        "head_sha": "a" * 40,
        "name": "tests",
        "path": ".github/workflows/python_tests.yml",
        "conclusion": "cancelled",
    }


def test_selection_preserves_diversity_and_caps_attempts():
    runs = [run(n) for n in range(1, 30)] + [run(0, 2)]
    selected = review.select_runs(runs)
    assert len(selected) == 20
    assert selected[:2] == [run(29), run(0, 2)]
    assert review.select_runs([]) == []


def test_redaction_omits_sensitive_lines_and_preserves_locations():
    files = {
        "job/1_step.txt": "normal\nwarning: token=hidden\n\x1b[31mdeprecated API https://example.org/?secret=value\n",
        "password.txt": "failure " + "x" * 600,
    }
    result = review.evidence_files(files)
    assert result[0]["excerpts"] == [
        {"line": 2, "text": "[omitted: potentially sensitive content]"},
        {"line": 3, "text": "[omitted: potentially sensitive content]"},
    ]
    assert "hidden" not in json.dumps(result)
    assert result[1]["source_file"].startswith("[omitted")
    assert len(result[1]["excerpts"][0]["text"]) == 500
    assert (
        review.safe_text("warning https://example.org/\x00") == "warning [URL omitted]"
    )
    result = review.evidence_files({"a": "warning\n" * 90})[0]
    assert len(result["excerpts"]) == 80
    assert result["omitted_signal_lines"] == 10


def test_inventory_tracks_api_truncation_and_deduplicates(monkeypatch):
    monkeypatch.setattr(review, "PAGE_LIMIT", 2)
    responses = iter(
        [
            {"total_count": 150, "workflow_runs": [run()] * 100},
            {"total_count": 0, "workflow_runs": []},
        ]
    )
    monkeypatch.setattr(review, "_get", lambda *a: next(responses))
    runs, complete, total = review.inventory(None, NOW)
    assert runs == [run()]
    assert not complete and total == 150
    monkeypatch.setattr(
        review, "_get", lambda *a: {"total_count": 100, "workflow_runs": [run()] * 100}
    )
    assert review.inventory(None, NOW)[1] is False
    monkeypatch.setattr(
        review, "_get", lambda *a: {"total_count": 1, "workflow_runs": [run()]}
    )
    assert review.inventory(None, NOW)[1] is True


def test_job_sources_preserves_step_numbers_and_page_limit(monkeypatch):
    job = {"id": 7, "name": "build", "steps": [{"number": 3, "name": "Run tool"}]}
    monkeypatch.setattr(review, "_get", lambda *a: {"jobs": [job]})
    result = review.job_sources(None, run())
    assert result["complete"]
    assert result["jobs"][0]["steps"] == [{"number": 3, "name": "Run tool"}]
    assert result["jobs"][0]["url"].endswith("/runs/1/job/7")
    monkeypatch.setattr(review, "PAGE_LIMIT", 1)
    monkeypatch.setattr(review, "_get", lambda *a: {"jobs": [job] * 100})
    assert review.job_sources(None, run())["complete"] is False


@pytest.mark.parametrize(
    "failure", [requests.HTTPError(), ValueError(), zipfile.BadZipFile(), OSError()]
)
def test_collect_reports_unavailable_without_exception_leaks(monkeypatch, failure):
    monkeypatch.setattr(review, "inventory", lambda *a: ([run()], True, 1))
    monkeypatch.setattr(review, "job_sources", Mock(side_effect=ValueError("secret")))
    monkeypatch.setattr(review, "fetch_workflow_log_files", Mock(side_effect=failure))
    result = review.collect(None, "private", NOW)
    entry = result["runs"][0]
    assert entry["attempt"] == 2 and entry["commit"] == "a" * 40
    assert entry["conclusion"] == "cancelled"
    assert entry["log_status"] == "unavailable" and entry["files"] == []
    assert entry["sources"] == {"complete": False, "jobs": []}
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize(
    "files,status", [({}, "empty"), ({"step.txt": "warning: deprecated"}, "available")]
)
def test_collect_uses_exact_attempt_and_reports_coverage(monkeypatch, files, status):
    monkeypatch.setattr(review, "inventory", lambda *a: ([run()], False, 2000))
    monkeypatch.setattr(
        review, "job_sources", lambda *a: {"complete": True, "jobs": []}
    )
    fetch = Mock(return_value=files)
    monkeypatch.setattr(review, "fetch_workflow_log_files", fetch)
    result = review.collect(None, "private", NOW)
    assert result["runs"][0]["log_status"] == status
    assert result["inventory_complete"] is False
    assert result["reported_total_runs"] == 2000
    assert fetch.call_args.kwargs["attempt"] == 2
    assert fetch.call_args.kwargs["retry_call"](lambda: "called") == "called"


def test_get_is_read_only_and_raises_for_http_errors():
    session = Mock()
    session.get.return_value.json.return_value = {"jobs": []}
    assert review._get(session, "actions/runs", {"page": 1}) == {"jobs": []}
    session.get.assert_called_once_with(
        f"https://api.github.com/repos/{review.REPOSITORY}/actions/runs",
        params={"page": 1},
        timeout=30,
    )
    session.get.return_value.raise_for_status.side_effect = requests.HTTPError()
    with pytest.raises(requests.HTTPError):
        review._get(session, "actions/runs")


def test_main_uses_gh_auth_without_emitting_credential(monkeypatch, capsys):
    monkeypatch.setattr(
        review.subprocess, "check_output", Mock(return_value="private\n")
    )
    collect = Mock(return_value={"runs": []})
    monkeypatch.setattr(review, "collect", collect)
    review.main()
    assert json.loads(capsys.readouterr().out) == {"runs": []}
    assert collect.call_args.args[1] == "private"


def test_shared_reader_preserves_archive_filenames():
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("job/", "")
        output.writestr("job/1_setup.txt", "warning one")
        output.writestr("job/2_build.txt", "warning two")
    session = Mock()
    session.get.return_value.content = archive.getvalue()
    files = workflows.fetch_workflow_log_files(
        session, review.REPOSITORY, 1, None, attempt=2
    )
    assert files == {"job/1_setup.txt": "warning one", "job/2_build.txt": "warning two"}
    assert session.get.call_args.args[0].endswith("/runs/1/attempts/2/logs")
