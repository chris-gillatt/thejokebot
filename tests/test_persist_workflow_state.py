import subprocess
from pathlib import Path
from unittest import mock

import pytest

from scripts import persist_workflow_state


def _completed(*, stdout: str = "", returncode: int = 0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


def _git(cwd: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _repository_with_remote(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    worktree = tmp_path / "worktree"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "init", "--initial-branch=main", str(worktree))
    _git(worktree, "config", "user.name", "Test Bot")
    _git(worktree, "config", "user.email", "bot@example.com")
    (worktree / "state").mkdir()
    (worktree / "state" / "social.json").write_text("initial\n", encoding="utf-8")
    (worktree / "README.md").write_text("initial\n", encoding="utf-8")
    _git(worktree, "add", ".")
    _git(worktree, "commit", "-m", "initial")
    _git(worktree, "remote", "add", "origin", str(remote))
    _git(worktree, "push", "--set-upstream", "origin", "main")
    _git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    return worktree, remote


def _clone_for_concurrent_update(tmp_path: Path, remote: Path) -> Path:
    concurrent = tmp_path / "concurrent"
    _git(tmp_path, "clone", str(remote), str(concurrent))
    _git(concurrent, "config", "user.name", "Concurrent Bot")
    _git(concurrent, "config", "user.email", "concurrent@example.com")
    return concurrent


def test_normalise_declared_path_accepts_safe_relative_paths():
    assert (
        persist_workflow_state._normalise_declared_path("state/file.json")
        == "state/file.json"
    )
    assert (
        persist_workflow_state._normalise_declared_path("dashboard/data/")
        == "dashboard/data"
    )


@pytest.mark.parametrize("value", ["", ".", "../state.json", "/tmp/state.json"])
def test_normalise_declared_path_rejects_unsafe_paths(value):
    with pytest.raises(persist_workflow_state.PersistenceError):
        persist_workflow_state._normalise_declared_path(value)


def test_assert_only_declared_changes_accepts_files_beneath_directory():
    with mock.patch.object(
        persist_workflow_state,
        "_changed_paths",
        side_effect=[{"dashboard/data/metrics.json"}, set()],
    ):
        persist_workflow_state._assert_only_declared_changes(("dashboard/data",))


def test_assert_only_declared_changes_rejects_unexpected_file():
    with mock.patch.object(
        persist_workflow_state,
        "_changed_paths",
        side_effect=[{"state/social_state.json", "README.md"}, set()],
    ):
        with pytest.raises(persist_workflow_state.PersistenceError, match="README.md"):
            persist_workflow_state._assert_only_declared_changes(
                ("state/social_state.json",)
            )


def test_persist_returns_without_commit_when_declared_files_are_unchanged():
    with (
        mock.patch.object(persist_workflow_state, "_assert_only_declared_changes"),
        mock.patch.object(persist_workflow_state, "_changed_paths", return_value=set()),
        mock.patch.object(persist_workflow_state, "_run_git") as run_git,
    ):
        assert not persist_workflow_state.persist(
            ["state/social_state.json"], commit_message="chore: state", branch="main"
        )
    run_git.assert_called_once_with(["add", "--all", "--", "state/social_state.json"])


def test_persist_commits_rebases_and_pushes_declared_changes():
    with (
        mock.patch.object(persist_workflow_state, "_assert_only_declared_changes"),
        mock.patch.object(
            persist_workflow_state,
            "_changed_paths",
            return_value={"state/social_state.json"},
        ),
        mock.patch.object(persist_workflow_state, "_run_git") as run_git,
        mock.patch.object(
            persist_workflow_state.subprocess,
            "run",
            side_effect=[_completed(returncode=1), _completed()],
        ) as run,
    ):
        assert persist_workflow_state.persist(
            ["state/social_state.json"],
            commit_message="chore: state",
            branch="main",
            max_attempts=2,
        )

    assert run_git.call_args_list == [
        mock.call(["add", "--all", "--", "state/social_state.json"]),
        mock.call(["commit", "-m", "chore: state"]),
        mock.call(["pull", "--rebase", "origin", "main"]),
        mock.call(["pull", "--rebase", "origin", "main"]),
    ]
    assert run.call_count == 2


def test_persist_fails_after_bounded_push_attempts():
    with (
        mock.patch.object(persist_workflow_state, "_assert_only_declared_changes"),
        mock.patch.object(
            persist_workflow_state, "_changed_paths", return_value={"state.json"}
        ),
        mock.patch.object(persist_workflow_state, "_run_git"),
        mock.patch.object(
            persist_workflow_state.subprocess,
            "run",
            return_value=_completed(returncode=1),
        ),
    ):
        with pytest.raises(persist_workflow_state.PersistenceError, match="2 attempts"):
            persist_workflow_state.persist(
                ["state.json"],
                commit_message="chore: state",
                branch="main",
                max_attempts=2,
            )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"declared_paths": []}, "At least one"),
        ({"commit_message": ""}, "commit message"),
        ({"branch": ""}, "branch and remote"),
        ({"remote": ""}, "branch and remote"),
        ({"max_attempts": 0}, "max_attempts"),
    ],
)
def test_persist_validates_arguments(kwargs, message):
    options = {
        "declared_paths": ["state.json"],
        "commit_message": "chore: state",
        "branch": "main",
        "remote": "origin",
        "max_attempts": 3,
    }
    options.update(kwargs)
    with pytest.raises(persist_workflow_state.PersistenceError, match=message):
        persist_workflow_state.persist(**options)


def test_main_reports_persistence_and_git_errors(capsys):
    for error in (
        persist_workflow_state.PersistenceError("unsafe"),
        subprocess.CalledProcessError(1, ["git"]),
    ):
        with mock.patch.object(persist_workflow_state, "persist", side_effect=error):
            assert (
                persist_workflow_state.main(
                    ["state.json", "--commit-message", "chore: state"]
                )
                == 1
            )
    assert "ERROR:" in capsys.readouterr().err


def test_main_returns_success(capsys):
    with mock.patch.object(persist_workflow_state, "persist", return_value=False):
        assert (
            persist_workflow_state.main(
                ["state.json", "--commit-message", "chore: state"]
            )
            == 0
        )
    assert capsys.readouterr().err == ""


def test_persist_pushes_declared_file_to_remote(tmp_path, monkeypatch):
    worktree, remote = _repository_with_remote(tmp_path)
    (worktree / "state" / "social.json").write_text("updated\n", encoding="utf-8")
    monkeypatch.chdir(worktree)

    assert persist_workflow_state.persist(
        ["state/social.json"], commit_message="chore: update state", branch="main"
    )

    assert _git(remote, "show", "main:state/social.json") == "updated\n"
    assert not _git(worktree, "status", "--porcelain")


def test_persist_refuses_unexpected_tracked_changes(tmp_path, monkeypatch):
    worktree, remote = _repository_with_remote(tmp_path)
    (worktree / "state" / "social.json").write_text("updated\n", encoding="utf-8")
    (worktree / "README.md").write_text("unexpected\n", encoding="utf-8")
    monkeypatch.chdir(worktree)

    with pytest.raises(persist_workflow_state.PersistenceError, match="README.md"):
        persist_workflow_state.persist(
            ["state/social.json"], commit_message="chore: update state", branch="main"
        )

    assert _git(remote, "show", "main:state/social.json") == "initial\n"
    assert _git(remote, "show", "main:README.md") == "initial\n"


def test_persist_rebases_over_remote_change_in_another_domain(tmp_path, monkeypatch):
    worktree, remote = _repository_with_remote(tmp_path)
    concurrent = _clone_for_concurrent_update(tmp_path, remote)
    (concurrent / "README.md").write_text("remote update\n", encoding="utf-8")
    _git(concurrent, "add", "README.md")
    _git(concurrent, "commit", "-m", "remote update")
    _git(concurrent, "push", "origin", "main")
    (worktree / "state" / "social.json").write_text("local state\n", encoding="utf-8")
    monkeypatch.chdir(worktree)

    assert persist_workflow_state.persist(
        ["state/social.json"], commit_message="chore: update state", branch="main"
    )

    assert _git(remote, "show", "main:state/social.json") == "local state\n"
    assert _git(remote, "show", "main:README.md") == "remote update\n"


def test_persist_fails_closed_on_same_file_rebase_conflict(tmp_path, monkeypatch):
    worktree, remote = _repository_with_remote(tmp_path)
    concurrent = _clone_for_concurrent_update(tmp_path, remote)
    (concurrent / "state" / "social.json").write_text(
        "remote state\n", encoding="utf-8"
    )
    _git(concurrent, "add", "state/social.json")
    _git(concurrent, "commit", "-m", "remote state")
    _git(concurrent, "push", "origin", "main")
    (worktree / "state" / "social.json").write_text("local state\n", encoding="utf-8")
    monkeypatch.chdir(worktree)

    with pytest.raises(subprocess.CalledProcessError):
        persist_workflow_state.persist(
            ["state/social.json"], commit_message="chore: update state", branch="main"
        )

    assert _git(remote, "show", "main:state/social.json") == "remote state\n"
