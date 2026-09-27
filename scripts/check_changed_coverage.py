#!/usr/bin/env python3
"""Enforce coverage for changed executable Python lines."""

from __future__ import annotations

import argparse
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path


class ChangedCoverageError(RuntimeError):
    """Raised when changed-line coverage cannot be calculated safely."""


def _run_git(arguments: Sequence[str]) -> str:
    try:
        return subprocess.run(
            ["git", *arguments],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or str(error)
        raise ChangedCoverageError(detail) from error


def _parse_changed_lines(diff: str) -> dict[str, set[int]]:
    changed: dict[str, set[int]] = defaultdict(set)
    current_path: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current_path = line[6:]
            continue
        if not line.startswith("@@ ") or current_path is None:
            continue
        try:
            new_range = line.split(" ")[2][1:]
            start_text, separator, count_text = new_range.partition(",")
            start = int(start_text)
            count = int(count_text) if separator else 1
        except (IndexError, ValueError) as error:
            raise ChangedCoverageError(f"Could not parse diff hunk: {line}") from error
        changed[current_path].update(range(start, start + count))
    return dict(changed)


def changed_python_lines(base: str) -> dict[str, set[int]]:
    diff = _run_git(
        [
            "diff",
            "--unified=0",
            "--no-ext-diff",
            "--diff-filter=AMCR",
            base,
            "--",
            "*.py",
        ]
    )
    changed = _parse_changed_lines(diff)
    untracked = _run_git(["ls-files", "--others", "--exclude-standard", "--", "*.py"])
    for filename in untracked.splitlines():
        path = Path(filename)
        try:
            line_count = len(path.read_text(encoding="utf-8").splitlines())
        except OSError as error:
            raise ChangedCoverageError(f"Could not read {filename}: {error}") from error
        changed[filename] = set(range(1, line_count + 1))
    return changed


def load_line_coverage(coverage_file: Path) -> dict[str, dict[int, int]]:
    try:
        root = ET.parse(coverage_file).getroot()
    except (OSError, ET.ParseError) as error:
        raise ChangedCoverageError(
            f"Could not read coverage report {coverage_file}: {error}"
        ) from error
    coverage: dict[str, dict[int, int]] = {}
    for class_element in root.findall(".//class"):
        filename = class_element.get("filename")
        if not filename:
            continue
        lines = {
            int(line.get("number", "0")): int(line.get("hits", "0"))
            for line in class_element.findall("./lines/line")
        }
        coverage[Path(filename).as_posix()] = lines
    return coverage


def calculate_changed_coverage(
    changed: dict[str, set[int]], coverage: dict[str, dict[int, int]]
) -> tuple[int, int, list[str]]:
    covered = 0
    executable = 0
    missed: list[str] = []
    for filename in sorted(changed):
        file_coverage = coverage.get(Path(filename).as_posix(), {})
        for line_number in sorted(changed[filename] & file_coverage.keys()):
            executable += 1
            if file_coverage[line_number] > 0:
                covered += 1
            else:
                missed.append(f"{filename}:{line_number}")
    return covered, executable, missed


def check_changed_coverage(base: str, coverage_file: Path, minimum: float) -> bool:
    changed = changed_python_lines(base)
    coverage = load_line_coverage(coverage_file)
    covered, executable, missed = calculate_changed_coverage(changed, coverage)
    if executable == 0:
        print("Changed-line coverage: no changed executable Python lines.")
        return True
    percentage = covered * 100 / executable
    print(
        f"Changed-line coverage: {percentage:.2f}% "
        f"({covered}/{executable}; required {minimum:.2f}%)."
    )
    if percentage >= minimum:
        return True
    if missed:
        print("Uncovered changed executable lines:")
        for location in missed:
            print(f"  - {location}")
    return False


def _parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="HEAD", help="Git revision to diff against.")
    parser.add_argument("--coverage-file", type=Path, default=Path("coverage.xml"))
    parser.add_argument("--minimum", type=float, default=95.0)
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    args = _parse_args(arguments)
    if not 0 <= args.minimum <= 100:
        print("ERROR: --minimum must be between 0 and 100.", file=sys.stderr)
        return 2
    try:
        passed = check_changed_coverage(args.base, args.coverage_file, args.minimum)
    except ChangedCoverageError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
