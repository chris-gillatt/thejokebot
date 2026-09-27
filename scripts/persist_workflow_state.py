#!/usr/bin/env python3
"""Safely commit and push explicitly declared workflow-generated files."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import PurePosixPath


class PersistenceError(RuntimeError):
    """Raised when workflow state cannot be persisted safely."""


def _run_git(
    arguments: Sequence[str],
    *,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # NOSONAR -- argv list, shell disabled; callers validate inputs.
        ["git", *arguments],
        check=True,
        text=True,
        capture_output=capture_output,
    )


def _normalise_declared_path(value: str) -> str:
    candidate = value.strip().replace("\\", "/")
    path = PurePosixPath(candidate)
    if (
        not candidate
        or path.is_absolute()
        or ".." in path.parts
        or path == PurePosixPath(".")
    ):
        raise PersistenceError(f"Declared path must be repository-relative: {value!r}")
    return path.as_posix().rstrip("/")


def _changed_paths(*, cached: bool = False) -> set[str]:
    arguments = ["diff", "--name-only", "-z"]
    if cached:
        arguments.append("--cached")
    result = _run_git(arguments, capture_output=True)
    return {path for path in result.stdout.split("\0") if path}


def _is_allowed(path: str, declared_paths: Sequence[str]) -> bool:
    return any(
        path == declared or path.startswith(f"{declared}/")
        for declared in declared_paths
    )


def _assert_only_declared_changes(declared_paths: Sequence[str]) -> None:
    changed = _changed_paths() | _changed_paths(cached=True)
    unexpected = sorted(
        path for path in changed if not _is_allowed(path, declared_paths)
    )
    if unexpected:
        formatted = "\n  - ".join(unexpected)
        raise PersistenceError(
            "Refusing to persist state because unexpected tracked files changed:\n"
            f"  - {formatted}"
        )


def persist(
    declared_paths: Sequence[str],
    *,
    commit_message: str,
    branch: str,
    remote: str = "origin",
    max_attempts: int = 3,
) -> bool:
    """Persist declared paths, returning whether a commit was created and pushed."""
    paths = tuple(_normalise_declared_path(path) for path in declared_paths)
    if not paths:
        raise PersistenceError("At least one path must be declared.")
    if not commit_message.strip():
        raise PersistenceError("The commit message must not be empty.")
    if not branch.strip() or not remote.strip():
        raise PersistenceError("The branch and remote must not be empty.")
    if branch != "main" or remote != "origin":
        raise PersistenceError(
            "Workflow state persistence is restricted to origin/main."
        )
    if max_attempts < 1:
        raise PersistenceError("max_attempts must be at least 1.")

    _assert_only_declared_changes(paths)
    _run_git(["add", "--all", "--", *paths])
    _assert_only_declared_changes(paths)

    if not _changed_paths(cached=True):
        print("No declared workflow state changes to commit.")
        return False

    _run_git(["commit", "-m", commit_message])
    for attempt in range(1, max_attempts + 1):
        _run_git(["pull", "--rebase", remote, branch])
        result = subprocess.run(  # NOSONAR -- fixed remote/branch, shell disabled.
            ["git", "push", remote, f"HEAD:{branch}"],
            check=False,
            text=True,
        )
        if result.returncode == 0:
            print("Workflow state committed and pushed.")
            return True
        if attempt == max_attempts:
            break
        print(f"Push rejected, retrying ({attempt}/{max_attempts})...")

    raise PersistenceError(f"Push failed after {max_attempts} attempts.")


def _parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths", nargs="+", help="Repository-relative files or directories to persist."
    )
    parser.add_argument("--commit-message", required=True)
    parser.add_argument("--branch", default=os.getenv("GITHUB_REF_NAME", "main"))
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--max-attempts", type=int, default=3)
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    args = _parse_args(arguments)
    try:
        persist(
            args.paths,
            commit_message=args.commit_message,
            branch=args.branch,
            remote=args.remote,
            max_attempts=args.max_attempts,
        )
    except (PersistenceError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
