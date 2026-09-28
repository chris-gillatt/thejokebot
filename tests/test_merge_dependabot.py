"""Safety checks for the Dependabot merge gate."""

import json
import sys
import subprocess
from unittest import mock

import pytest

from scripts import merge_dependabot


def _pr(number=125, *, bot_id=merge_dependabot.DEPENDABOT_ID):
    return {
        "number": number,
        "user": {"id": bot_id},
        "head": {"sha": "current-head", "repo": {"full_name": "owner/repo"}},
        "base": {"ref": "main"},
        "draft": False,
    }


def _checks():
    return [
        {
            "__typename": "CheckRun",
            "name": name,
            "status": "COMPLETED",
            "conclusion": "SUCCESS",
        }
        for name in merge_dependabot.REQUIRED_CHECKS
    ]


def test_requires_all_successful_checks():
    checks = _checks()
    assert merge_dependabot._checks_passed(checks)
    assert not merge_dependabot._checks_passed(checks[:-1])
    checks[0]["conclusion"] = "SKIPPED"
    assert not merge_dependabot._checks_passed(checks)
    checks = _checks() + [
        {"__typename": "StatusContext", "context": "security", "state": "FAILURE"}
    ]
    assert not merge_dependabot._checks_passed(checks)


def test_restricts_author_and_changed_files():
    assert merge_dependabot._eligible(_pr(), "owner/repo")
    assert not merge_dependabot._eligible(_pr(bot_id=1), "owner/repo")
    assert merge_dependabot._allowed_path(".github/workflows/codeql.yml")
    assert merge_dependabot._allowed_path("requirements.lock")
    assert not merge_dependabot._allowed_path("src/thejokebot/runtime.py")
    assert not merge_dependabot._allowed_path(".github/workflows/nested/other.yml")


def test_merges_only_the_checked_head():
    detail = {
        "headRefOid": "current-head",
        "mergeStateStatus": "CLEAN",
        "statusCheckRollup": _checks(),
    }
    with (
        mock.patch.dict("os.environ", {"DEPENDABOT_WORKFLOW_TOKEN": "scoped-token"}),
        mock.patch.object(
            merge_dependabot,
            "_gh",
            side_effect=[
                json.dumps([_pr()]),
                json.dumps([[{"filename": ".github/workflows/codeql.yml"}]]),
                json.dumps(detail),
                "merged",
            ],
        ) as gh,
    ):
        assert merge_dependabot.merge_ready_prs("owner/repo") == 1
    assert gh.call_args.args == (
        "pr",
        "merge",
        "125",
        "--repo",
        "owner/repo",
        "--squash",
        "--match-head-commit",
        "current-head",
    )
    assert gh.call_args.kwargs == {"token": "scoped-token"}


def test_dry_run_never_merges_and_changed_head_is_skipped():
    detail = {
        "headRefOid": "other-head",
        "mergeStateStatus": "CLEAN",
        "statusCheckRollup": _checks(),
    }
    with mock.patch.object(
        merge_dependabot,
        "_gh",
        side_effect=[
            json.dumps([_pr()]),
            json.dumps([[{"filename": "package-lock.json"}]]),
            json.dumps(detail),
        ],
    ) as gh:
        assert merge_dependabot.merge_ready_prs("owner/repo", dry_run=True) == 0
    assert gh.call_count == 3


def test_rejects_untrusted_author_and_non_dependency_files():
    with mock.patch.object(
        merge_dependabot, "_gh", return_value=json.dumps([_pr(bot_id=1)])
    ) as gh:
        assert merge_dependabot.merge_ready_prs("owner/repo") == 0
        gh.assert_called_once()

    with mock.patch.object(
        merge_dependabot,
        "_gh",
        side_effect=[
            json.dumps([_pr()]),
            json.dumps([[{"filename": "src/thejokebot/runtime.py"}]]),
        ],
    ) as gh:
        assert merge_dependabot.merge_ready_prs("owner/repo") == 0
        assert gh.call_count == 2


def test_waits_for_clean_merge_and_checks():
    detail = {
        "headRefOid": "current-head",
        "mergeStateStatus": "DIRTY",
        "statusCheckRollup": _checks(),
    }
    with mock.patch.object(
        merge_dependabot,
        "_gh",
        side_effect=[
            json.dumps([_pr()]),
            json.dumps([[{"filename": "package.json"}]]),
            json.dumps(detail),
        ],
    ) as gh:
        assert merge_dependabot.merge_ready_prs("owner/repo") == 0
        assert gh.call_count == 3


def test_dry_run_reports_ready_without_merging():
    detail = {
        "headRefOid": "current-head",
        "mergeStateStatus": "CLEAN",
        "statusCheckRollup": _checks(),
    }
    with mock.patch.object(
        merge_dependabot,
        "_gh",
        side_effect=[
            json.dumps([_pr()]),
            json.dumps([[{"filename": "requirements.lock"}]]),
            json.dumps(detail),
        ],
    ) as gh:
        assert merge_dependabot.merge_ready_prs("owner/repo", dry_run=True) == 1
        assert gh.call_count == 3


def test_workflow_update_waits_for_separate_token():
    detail = {
        "headRefOid": "current-head",
        "mergeStateStatus": "CLEAN",
        "statusCheckRollup": _checks(),
    }
    with (
        mock.patch.dict("os.environ", {}, clear=True),
        mock.patch.object(
            merge_dependabot,
            "_gh",
            side_effect=[
                json.dumps([_pr()]),
                json.dumps([[{"filename": ".github/workflows/codeql.yml"}]]),
                json.dumps(detail),
            ],
        ) as gh,
    ):
        assert merge_dependabot.merge_ready_prs("owner/repo") == 0
        assert gh.call_count == 3


def test_invalid_repository_and_cli_error_are_visible(capsys):
    with mock.patch.object(merge_dependabot, "_gh") as gh:
        try:
            merge_dependabot.merge_ready_prs("invalid")
        except ValueError:
            pass
        else:
            raise AssertionError("invalid repository was accepted")
        gh.assert_not_called()

    with (
        mock.patch.object(sys, "argv", ["merge_dependabot.py"]),
        mock.patch.dict("os.environ", {"GITHUB_REPOSITORY": "owner/repo"}),
        mock.patch.object(
            merge_dependabot, "merge_ready_prs", side_effect=ValueError("bad")
        ),
    ):
        assert merge_dependabot.main() == 1
    assert "bad" in capsys.readouterr().err


def test_cli_passes_dry_run_and_gh_uses_argv(capsys):
    with (
        mock.patch.object(sys, "argv", ["merge_dependabot.py", "--dry-run"]),
        mock.patch.dict("os.environ", {"GITHUB_REPOSITORY": "owner/repo"}),
        mock.patch.object(merge_dependabot, "merge_ready_prs", return_value=1) as merge,
    ):
        assert merge_dependabot.main() == 0
    merge.assert_called_once_with("owner/repo", dry_run=True)
    assert "Ready to merge 1" in capsys.readouterr().out

    with mock.patch.object(
        subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "ok")
    ) as run:
        assert merge_dependabot._gh("pr", "list") == "ok"
    run.assert_called_once_with(
        ["gh", "pr", "list"], check=True, text=True, capture_output=True, env=None
    )

    with mock.patch.object(
        subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "ok")
    ) as run:
        assert merge_dependabot._gh("pr", "merge", token="scoped-token") == "ok"
    assert run.call_args.kwargs["env"]["GH_TOKEN"] == "scoped-token"

    failure = subprocess.CalledProcessError(
        1, ["gh", "pr", "merge"], stderr="merge declined"
    )
    with (
        mock.patch.object(subprocess, "run", side_effect=failure),
        pytest.raises(RuntimeError, match="merge declined"),
    ):
        merge_dependabot._gh("pr", "merge")
