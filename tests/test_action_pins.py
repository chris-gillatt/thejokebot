import json
import subprocess
from unittest import mock

import pytest

from scripts import check_action_pins, lint_action_workflows


def test_unpinned_actions_rejects_mutable_remote_references():
    text = "steps:\n  - uses: actions/checkout@v7\n  - uses: owner/action@main\n"
    assert check_action_pins.unpinned_actions(text, "workflow.yml") == [
        "workflow.yml:2: actions/checkout@v7",
        "workflow.yml:3: owner/action@main",
    ]


def test_unpinned_actions_allows_sha_local_and_docker_references():
    sha = "a" * 40
    text = f"steps:\n  - uses: owner/action@{sha}\n  - uses: ./local\n  - uses: docker://alpine:3\n"
    assert check_action_pins.unpinned_actions(text, "workflow.yml") == []


def test_check_workflows_reads_yaml_extensions(tmp_path):
    (tmp_path / "one.yml").write_text("- uses: owner/action@v1\n", encoding="utf-8")
    (tmp_path / "two.yaml").write_text(
        f"- uses: owner/action@{'b' * 40}\n", encoding="utf-8"
    )
    assert check_action_pins.check_workflows(tmp_path) == [
        f"{tmp_path / 'one.yml'}:1: owner/action@v1"
    ]


def test_main_reports_success_and_failure(tmp_path, capsys):
    assert check_action_pins.main([str(tmp_path)]) == 0
    (tmp_path / "bad.yml").write_text("uses: owner/action@v1\n", encoding="utf-8")
    assert check_action_pins.main([str(tmp_path)]) == 1
    assert "full commit SHA" in capsys.readouterr().err
    with mock.patch.object(
        check_action_pins, "check_workflows", side_effect=OSError("unreadable")
    ):
        assert check_action_pins.main([str(tmp_path)]) == 2
    assert "unreadable" in capsys.readouterr().err


def queue_error():
    return {
        "kind": "syntax-check",
        "message": lint_action_workflows.QUEUE_DIAGNOSTIC,
        "filepath": ".github/workflows/reviews.yml",
        "line": 3,
        "column": 3,
    }


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        "wrong-value",
        "cancel-running",
        "wrong-group",
        "wrong-location",
        "different-diagnostic",
        "bad-line",
        "external-file",
    ],
)
def test_queue_exception_accepts_only_the_supported_shared_writer_block(
    tmp_path, invalid
):
    error = queue_error()
    content = "concurrency:\n  group: joke_and_social_state_writer\n  queue: max\n  cancel-in-progress: false\n"
    if invalid == "wrong-value":
        content = content.replace("queue: max", "queue: invalid")
    elif invalid == "cancel-running":
        content = content.replace("false", "true")
    elif invalid == "wrong-group":
        content = content.replace("joke_and_social_state_writer", "other-group")
    elif invalid == "wrong-location":
        content = content.replace("concurrency:", "env:")
    elif invalid == "different-diagnostic":
        error["message"] = "Another workflow syntax error"
    elif invalid == "bad-line":
        error["line"] = 99
    elif invalid == "external-file":
        error["filepath"] = "references/external.yml"
    path = tmp_path / ".github/workflows/reviews.yml"
    path.parent.mkdir(parents=True)
    path.write_text(content)
    assert lint_action_workflows.verified_queue_diagnostic(error, tmp_path) is (
        invalid is None
    )


@pytest.mark.parametrize(
    "result", ["success", "verified-queue", "real-error", "tool-error"]
)
@pytest.mark.parametrize("docker", [False, True])
def test_queue_aware_lint_preserves_other_errors(
    tmp_path, monkeypatch, capsys, result, docker
):
    error = queue_error()
    path = tmp_path / error["filepath"]
    path.parent.mkdir(parents=True)
    path.write_text(
        "concurrency:\n  group: joke_and_social_state_writer\n  queue: max\n  cancel-in-progress: false\n"
    )
    monkeypatch.setattr(lint_action_workflows, "ROOT", tmp_path)
    response = subprocess.CompletedProcess([], 1, json.dumps([error]), "")
    if result == "success":
        response.returncode = 0
    elif result == "real-error":
        response.stdout = json.dumps(
            [error, {**error, "message": "Actual syntax failure"}]
        )
    elif result == "tool-error":
        response.returncode = 2
        response.stderr = "Failed to execute actionlint"
    monkeypatch.setattr(
        lint_action_workflows.subprocess, "run", mock.Mock(return_value=response)
    )
    assert lint_action_workflows.main(["--docker"] if docker else []) == (
        0
        if result in ("success", "verified-queue")
        else (2 if result == "tool-error" else 1)
    )
    if result == "real-error":
        assert "Actual syntax failure" in capsys.readouterr().err
