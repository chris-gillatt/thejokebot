#!/usr/bin/env python3
"""Merge Dependabot PRs after the expected checks pass on their current head."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import argparse

DEPENDABOT_ID = 49699333
REQUIRED_CHECKS = frozenset(
    {
        "tests",
        "ruff",
        "validate_runtime_config",
        "Analyse (Python) (python)",
        "CodeQL",
        "SonarCloud Code Analysis",
    }
)
DEPENDENCY_FILES = frozenset(
    {"requirements.lock", "pyproject.toml", "package.json", "package-lock.json"}
)


def _gh(*arguments: str) -> str:
    try:
        return subprocess.run(
            ["gh", *arguments], check=True, text=True, capture_output=True
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"GitHub CLI failed: {exc.stderr.strip()}") from exc


def _allowed_path(path: str) -> bool:
    return path in DEPENDENCY_FILES or (
        path.startswith(".github/workflows/")
        and path.endswith((".yml", ".yaml"))
        and path.count("/") == 2
    )


def _checks_passed(checks: list[dict]) -> bool:
    seen: set[str] = set()
    for check in checks:
        name = check.get("name") or check.get("context")
        if check.get("__typename") == "StatusContext":
            if check.get("state") != "SUCCESS":
                return False
        elif check.get("status") != "COMPLETED" or check.get("conclusion") != "SUCCESS":
            return False
        if name in REQUIRED_CHECKS:
            seen.add(name)
    return seen == REQUIRED_CHECKS


def _eligible(pr: dict, repository: str) -> bool:
    return (
        pr.get("user", {}).get("id") == DEPENDABOT_ID
        and pr.get("head", {}).get("repo", {}).get("full_name") == repository
        and pr.get("base", {}).get("ref") == "main"
        and not pr.get("draft")
    )


def merge_ready_prs(repository: str, *, dry_run: bool = False) -> int:
    if not repository or "/" not in repository:
        raise ValueError("GITHUB_REPOSITORY must identify an owner and repository")
    prs = json.loads(
        _gh(
            "api",
            "--method",
            "GET",
            f"repos/{repository}/pulls",
            "-f",
            "state=open",
            "-f",
            "per_page=100",
        )
    )
    merged = 0
    for pr in prs:
        number = pr["number"]
        if not _eligible(pr, repository):
            continue
        pages = json.loads(
            _gh(
                "api",
                "--paginate",
                "--slurp",
                f"repos/{repository}/pulls/{number}/files",
            )
        )
        files = [file for page in pages for file in page]
        if not files or any(not _allowed_path(file["filename"]) for file in files):
            print(f"PR #{number}: unexpected changed files; awaiting review.")
            continue
        detail = json.loads(
            _gh(
                "pr",
                "view",
                str(number),
                "--repo",
                repository,
                "--json",
                "headRefOid,mergeStateStatus,statusCheckRollup",
            )
        )
        if detail["headRefOid"] != pr["head"]["sha"]:
            print(f"PR #{number}: head changed while checking; will retry later.")
            continue
        if detail["mergeStateStatus"] != "CLEAN" or not _checks_passed(
            detail.get("statusCheckRollup") or []
        ):
            print(f"PR #{number}: waiting for a clean merge and all required checks.")
            continue
        if dry_run:
            print(f"PR #{number}: ready to merge (dry run).")
        else:
            _gh(
                "pr",
                "merge",
                str(number),
                "--repo",
                repository,
                "--squash",
                "--match-head-commit",
                detail["headRefOid"],
            )
            print(f"PR #{number}: merged verified Dependabot update.")
        merged += 1
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        merged = merge_ready_prs(
            os.getenv("GITHUB_REPOSITORY", ""), dry_run=args.dry_run
        )
    except (
        ValueError,
        KeyError,
        json.JSONDecodeError,
        RuntimeError,
    ) as exc:
        print(f"Dependabot merge gate failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"{'Ready to merge' if args.dry_run else 'Merged'} {merged} Dependabot PR(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
