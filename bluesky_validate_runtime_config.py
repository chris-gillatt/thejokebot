"""Validate central runtime config schema and workflow schedule alignment."""

from __future__ import annotations

import re
from pathlib import Path

import bluesky_config

WORKFLOW_FILES = {
    "bluesky_post_joke": ".github/workflows/bluesky_post_joke.yml",
    "bluesky_dashboard": ".github/workflows/bluesky_dashboard.yml",
    "bluesky_follows_and_likes": ".github/workflows/bluesky_follows_and_likes.yml",
    "bluesky_follow_fellows": ".github/workflows/bluesky_follow_fellows.yml",
    "bluesky_unfollow": ".github/workflows/bluesky_unfollow.yml",
    "bluesky_process_reports": ".github/workflows/bluesky_process_reports.yml",
    "bluesky_validate_unfollow_ignore": ".github/workflows/bluesky_validate_unfollow_ignore.yml",
}

_WORKFLOW_PATH_PREFIX = ".github/workflows/"
_WORKFLOW_FALLBACK_PREFIX = ".github/workflows-disabled/"

_CRON_PATTERN = re.compile(r'^\s*-\s*cron:\s*"([^"]+)"(?:\s+#.*)?\s*$', re.MULTILINE)


def _estimate_runs_per_week(cron: str) -> float | None:
    return bluesky_config.estimate_runs_per_week(cron)


def _validate_guard_rails(config: dict, schedules: dict[str, str]) -> list[str]:
    errors: list[str] = []

    reports_cfg = config.get("reports", {})
    follow_cfg = config.get("follow_fellows", {})
    unfollow_cfg = config.get("unfollow", {})

    reports_rate = _estimate_runs_per_week(schedules.get("bluesky_process_reports", ""))
    if reports_rate is not None and reports_rate > 336:
        if reports_cfg.get("max_pages", 0) > 3:
            errors.append(
                "Guard rail: reports.max_pages must be <= 3 when bluesky_process_reports runs more than every 30 minutes."
            )

    follow_rate = _estimate_runs_per_week(schedules.get("bluesky_follow_fellows", ""))
    if follow_rate is not None and follow_rate > 3:
        if follow_cfg.get("global_follow_limit", 0) > 150:
            errors.append(
                "Guard rail: follow_fellows.global_follow_limit must be <= 150 when bluesky_follow_fellows runs more than 3 times per week."
            )

    unfollow_rate = _estimate_runs_per_week(schedules.get("bluesky_unfollow", ""))
    if unfollow_rate is not None and unfollow_rate > 7:
        if unfollow_cfg.get("max_actions", 0) > 200:
            errors.append(
                "Guard rail: unfollow.max_actions must be <= 200 when bluesky_unfollow runs more than once per day."
            )

    return errors


def _extract_cron(workflow_path: Path) -> str | None:
    try:
        content = workflow_path.read_text(encoding="utf-8")
    except OSError:
        return None

    match = _CRON_PATTERN.search(content)
    if not match:
        return None
    return match.group(1).strip()


def _extract_cron_with_fallback(relative_path: str) -> tuple[str | None, str]:
    primary = Path(relative_path)
    actual = _extract_cron(primary)
    if actual:
        return actual, relative_path

    if relative_path.startswith(_WORKFLOW_PATH_PREFIX):
        fallback_path = (
            _WORKFLOW_FALLBACK_PREFIX + relative_path[len(_WORKFLOW_PATH_PREFIX) :]
        )
        fallback = Path(fallback_path)
        actual = _extract_cron(fallback)
        if actual:
            return actual, fallback_path

    return None, relative_path


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

        actual, resolved_path = _extract_cron_with_fallback(relative_path)
        if not actual:
            errors.append(
                f"Could not read cron schedule from workflow file: {relative_path}"
            )
            continue

        if configured != actual:
            errors.append(
                f"Schedule mismatch for {key}: config='{configured}' workflow='{actual}' (from {resolved_path})"
            )

    errors.extend(_validate_guard_rails(config, schedules))

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
