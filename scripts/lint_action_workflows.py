#!/usr/bin/env python3
"""Run actionlint with a verified exception for its concurrency queue schema gap."""

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUEUE_DIAGNOSTIC = (
    'unexpected key "queue" for "concurrency" section. '
    'expected one of "cancel-in-progress", "group"'
)


def verified_queue_diagnostic(error: dict, root: Path) -> bool:
    if error["kind"] != "syntax-check" or error["message"] != QUEUE_DIAGNOSTIC:
        return False
    path = (root / error["filepath"]).resolve()
    if not path.is_relative_to(root / ".github" / "workflows"):
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    index = error["line"] - 1
    if index < 2:
        return False
    # Only this exact supported block may bypass the upstream parser gap.
    block = lines[index - 2 : index + 2]
    shared_queue = [
        "concurrency:",
        "  group: joke_and_social_state_writer",
        "  queue: max",
        "  cancel-in-progress: false",
    ]
    # Fellow discovery acquires the same queue at job scope after its timer.
    return block == shared_queue or (
        path == root / ".github/workflows/bluesky_follow_fellows.yml"
        and block == [f"    {line}" for line in shared_queue]
    )


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", action="store_true")
    args = parser.parse_args(arguments)
    command = (
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{ROOT}:/repo",
            "-w",
            "/repo",
            "rhysd/actionlint:latest",
        ]
        if args.docker
        else ["actionlint"]
    )
    result = subprocess.run(
        [*command, "-format", "{{json .}}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        print("Workflow lint passed.")
        return 0
    if result.returncode != 1 or not result.stdout.strip() or result.stderr.strip():
        print(result.stdout + result.stderr, file=sys.stderr)
        return result.returncode
    errors = json.loads(result.stdout)
    if not isinstance(errors, list) or not errors:
        raise ValueError("Unexpected actionlint diagnostics")
    failures = [error for error in errors if not verified_queue_diagnostic(error, ROOT)]
    for error in failures:
        print(
            f"{error['filepath']}:{error['line']}:{error['column']}: "
            f"{error['message']} [{error['kind']}]",
            file=sys.stderr,
        )
    if failures:
        return 1
    print("Workflow lint passed with verified queue support (rhysd/actionlint#657).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
