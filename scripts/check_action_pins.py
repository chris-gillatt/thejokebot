#!/usr/bin/env python3
"""Reject mutable GitHub Action references in workflow files."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)")
_SHA = re.compile(r"^[0-9a-f]{40}$")


def unpinned_actions(text: str, filename: str) -> list[str]:
    failures = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = _USES.match(line)
        if not match:
            continue
        reference = match.group(1)
        if reference.startswith("./") or reference.startswith("docker://"):
            continue
        _, separator, revision = reference.rpartition("@")
        if not separator or not _SHA.fullmatch(revision):
            failures.append(f"{filename}:{line_number}: {reference}")
    return failures


def check_workflows(directory: Path) -> list[str]:
    failures = []
    paths = (*directory.glob("*.yml"), *directory.glob("*.yaml"))
    for path in sorted(paths):
        failures.extend(unpinned_actions(path.read_text(encoding="utf-8"), str(path)))
    return failures


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory", type=Path, nargs="?", default=Path(".github/workflows")
    )
    args = parser.parse_args(arguments)
    try:
        failures = check_workflows(args.directory)
    except OSError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if failures:
        print("Remote actions must be pinned to a full commit SHA:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("All remote GitHub Actions are pinned to full commit SHAs.")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by workflow shell entry
    raise SystemExit(main())
