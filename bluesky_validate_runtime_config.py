"""Validate central runtime config schema and workflow schedule alignment."""

from __future__ import annotations

import re
from pathlib import Path

import bluesky_config

WORKFLOW_FILES = {
    "bluesky_post_joke": ".github/workflows/bluesky_post_joke.yml",
    "bluesky_follows_and_likes": ".github/workflows/bluesky_follows_and_likes.yml",
    "bluesky_follow_fellows": ".github/workflows/bluesky_follow_fellows.yml",
    "bluesky_unfollow": ".github/workflows/bluesky_unfollow.yml",
    "bluesky_process_reports": ".github/workflows/bluesky_process_reports.yml",
    "bluesky_validate_unfollow_ignore": ".github/workflows/bluesky_validate_unfollow_ignore.yml",
}

_CRON_PATTERN = re.compile(
    r'^\s*-\s*cron:\s*"([^"]+)"(?:\s+#.*)?\s*$', re.MULTILINE
)


def _extract_cron(workflow_path: Path) -> str | None:
    try:
        content = workflow_path.read_text(encoding="utf-8")
    except OSError:
        return None

    match = _CRON_PATTERN.search(content)
    if not match:
        return None
    return match.group(1).strip()


def validate_runtime_config() -> list[str]:
    errors: list[str] = []

    try:
        config = bluesky_config.load_runtime_config(strict=True)
    except (FileNotFoundError, ValueError) as exc:
        return [str(exc)]

    schedules = config.get("workflow_schedules", {})
    if not isinstance(schedules, dict):
        return ["workflow_schedules must be an object in runtime config."]

    for key, relative_path in WORKFLOW_FILES.items():
        configured = str(schedules.get(key, "")).strip()
        if not configured:
            errors.append(f"Missing workflow_schedules.{key} in runtime config.")
            continue

        actual = _extract_cron(Path(relative_path))
        if not actual:
            errors.append(
                f"Could not read cron schedule from workflow file: {relative_path}"
            )
            continue

        if configured != actual:
            errors.append(
                f"Schedule mismatch for {key}: config='{configured}' workflow='{actual}'"
            )

    return errors


def main() -> int:
    errors = validate_runtime_config()
    if errors:
        print("Runtime config validation failed:")
        for err in errors:
            print(f"- {err}")
        return 1

    print("Runtime config validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
