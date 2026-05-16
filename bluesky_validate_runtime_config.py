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

_CRON_PATTERN = re.compile(r'^\s*-\s*cron:\s*"([^"]+)"(?:\s+#.*)?\s*$', re.MULTILINE)


def _parse_cron_parts(cron: str) -> tuple[str, str, str, str, str] | None:
    parts = cron.split()
    if len(parts) != 5:
        return None
    return tuple(parts)  # type: ignore[return-value]


def _count_field_values(field: str, minimum: int, maximum: int) -> int | None:
    if field == "*":
        return maximum - minimum + 1
    if field.startswith("*/"):
        try:
            step = int(field[2:])
        except ValueError:
            return None
        if step <= 0:
            return None
        span = maximum - minimum + 1
        return (span + step - 1) // step

    values = field.split(",")
    count = 0
    for value in values:
        value = value.strip()
        if not value:
            return None
        if not value.isdigit():
            return None
        ivalue = int(value)
        if ivalue < minimum or ivalue > maximum:
            return None
        count += 1
    return count


def _estimate_runs_per_week(cron: str) -> float | None:
    parts = _parse_cron_parts(cron)
    if not parts:
        return None
    minute, hour, day_of_month, month, day_of_week = parts

    minute_count = _count_field_values(minute, 0, 59)
    hour_count = _count_field_values(hour, 0, 23)
    if minute_count is None or hour_count is None:
        return None

    # Daily/Hourly style schedules.
    if day_of_month == "*" and month == "*" and day_of_week == "*":
        return float(minute_count * hour_count * 7)

    # Weekly schedules using day-of-week only.
    if day_of_month == "*" and month == "*" and day_of_week != "*":
        dow_count = _count_field_values(day_of_week, 0, 6)
        if dow_count is None:
            return None
        return float(minute_count * hour_count * dow_count)

    # Monthly schedules on a fixed day.
    if day_of_month.isdigit() and month == "*" and day_of_week == "*":
        return float(minute_count * hour_count) / 4.345

    # Monthly schedules with month step (for example */3).
    if day_of_month.isdigit() and month.startswith("*/") and day_of_week == "*":
        try:
            month_step = int(month[2:])
        except ValueError:
            return None
        if month_step <= 0:
            return None
        return float(minute_count * hour_count) / (4.345 * month_step)

    return None


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
