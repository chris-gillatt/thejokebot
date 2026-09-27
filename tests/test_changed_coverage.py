import subprocess
from unittest import mock

import pytest

from scripts import check_changed_coverage


def test_parse_changed_lines_handles_additions_modifications_and_deletions():
    diff = """\
diff --git a/example.py b/example.py
--- a/example.py
+++ b/example.py
@@ -2 +2,2 @@
@@ -8,2 +9,0 @@
diff --git a/new.py b/new.py
--- /dev/null
+++ b/new.py
@@ -0,0 +1,3 @@
"""
    assert check_changed_coverage._parse_changed_lines(diff) == {
        "example.py": {2, 3},
        "new.py": {1, 2, 3},
    }


def test_parse_changed_lines_rejects_malformed_hunk():
    with pytest.raises(check_changed_coverage.ChangedCoverageError):
        check_changed_coverage._parse_changed_lines(
            "+++ b/example.py\n@@ -1 +invalid @@"
        )


def test_load_line_coverage_reads_executable_lines(tmp_path):
    report = tmp_path / "coverage.xml"
    report.write_text(
        '<coverage><packages><package><classes><class filename="src/example.py">'
        '<lines><line number="2" hits="1"/><line number="3" hits="0"/></lines>'
        "</class></classes></package></packages></coverage>",
        encoding="utf-8",
    )
    assert check_changed_coverage.load_line_coverage(report) == {
        "src/example.py": {2: 1, 3: 0}
    }


@pytest.mark.parametrize("content", ["not xml", ""])
def test_load_line_coverage_rejects_invalid_report(tmp_path, content):
    report = tmp_path / "coverage.xml"
    report.write_text(content, encoding="utf-8")
    with pytest.raises(check_changed_coverage.ChangedCoverageError):
        check_changed_coverage.load_line_coverage(report)


def test_calculate_changed_coverage_ignores_non_executable_and_deleted_lines():
    covered, executable, missed = check_changed_coverage.calculate_changed_coverage(
        {"example.py": {2, 3, 4}, "deleted.py": {1}},
        {"example.py": {2: 1, 3: 0}},
    )
    assert (covered, executable, missed) == (1, 2, ["example.py:3"])


def test_changed_python_lines_includes_untracked_python(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "new.py").write_text("one\ntwo\n", encoding="utf-8")
    with mock.patch.object(
        check_changed_coverage,
        "_run_git",
        side_effect=[
            "a" * 40 + "\n",
            "+++ b/tracked.py\n@@ -0,0 +4 @@",
            "new.py\n",
        ],
    ):
        assert check_changed_coverage.changed_python_lines("HEAD") == {
            "tracked.py": {4},
            "new.py": {1, 2},
        }


def test_changed_python_lines_reports_unreadable_untracked_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with (
        mock.patch.object(
            check_changed_coverage,
            "_run_git",
            side_effect=["a" * 40 + "\n", "", "missing.py\n"],
        ),
        pytest.raises(check_changed_coverage.ChangedCoverageError, match="missing.py"),
    ):
        check_changed_coverage.changed_python_lines("HEAD")


@pytest.mark.parametrize("base", ["", "--output=/tmp/result", "bad\x00revision"])
def test_resolve_base_rejects_unsafe_revision(base):
    with pytest.raises(check_changed_coverage.ChangedCoverageError, match="Invalid"):
        check_changed_coverage._resolve_base(base)


def test_resolve_base_requires_full_commit_sha():
    with mock.patch.object(check_changed_coverage, "_run_git", return_value="HEAD\n"):
        with pytest.raises(
            check_changed_coverage.ChangedCoverageError, match="commit SHA"
        ):
            check_changed_coverage._resolve_base("HEAD")


def test_run_git_wraps_failure():
    failure = subprocess.CalledProcessError(1, ["git"], stderr="bad revision")
    with (
        mock.patch.object(
            check_changed_coverage.subprocess, "run", side_effect=failure
        ),
        pytest.raises(
            check_changed_coverage.ChangedCoverageError, match="bad revision"
        ),
    ):
        check_changed_coverage._run_git(["diff"])


def test_check_changed_coverage_passes_empty_and_threshold(tmp_path, capsys):
    with (
        mock.patch.object(
            check_changed_coverage, "changed_python_lines", return_value={}
        ),
        mock.patch.object(
            check_changed_coverage, "load_line_coverage", return_value={}
        ),
    ):
        assert check_changed_coverage.check_changed_coverage("HEAD", tmp_path / "x", 95)

    with (
        mock.patch.object(
            check_changed_coverage,
            "changed_python_lines",
            return_value={"example.py": {1, 2}},
        ),
        mock.patch.object(
            check_changed_coverage,
            "load_line_coverage",
            return_value={"example.py": {1: 1, 2: 1}},
        ),
    ):
        assert check_changed_coverage.check_changed_coverage("HEAD", tmp_path / "x", 95)
    assert "100.00%" in capsys.readouterr().out


def test_check_changed_coverage_fails_and_lists_missed_lines(tmp_path, capsys):
    with (
        mock.patch.object(
            check_changed_coverage,
            "changed_python_lines",
            return_value={"example.py": {1, 2}},
        ),
        mock.patch.object(
            check_changed_coverage,
            "load_line_coverage",
            return_value={"example.py": {1: 1, 2: 0}},
        ),
    ):
        assert not check_changed_coverage.check_changed_coverage(
            "HEAD", tmp_path / "x", 95
        )
    assert "example.py:2" in capsys.readouterr().out


def test_main_returns_success_failure_and_usage_error(tmp_path, capsys):
    with mock.patch.object(
        check_changed_coverage, "check_changed_coverage", return_value=True
    ):
        assert (
            check_changed_coverage.main(["--coverage-file", str(tmp_path / "x")]) == 0
        )
    with mock.patch.object(
        check_changed_coverage, "check_changed_coverage", return_value=False
    ):
        assert (
            check_changed_coverage.main(["--coverage-file", str(tmp_path / "x")]) == 1
        )
    assert check_changed_coverage.main(["--minimum", "101"]) == 2
    with mock.patch.object(
        check_changed_coverage,
        "check_changed_coverage",
        side_effect=check_changed_coverage.ChangedCoverageError("broken"),
    ):
        assert check_changed_coverage.main([]) == 2
    assert "ERROR:" in capsys.readouterr().err
