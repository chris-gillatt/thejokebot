"""Durable, fixed-age observations of public bot posts."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from thejokebot.paths import STATE_DIR

STATE_FILE = STATE_DIR / "dashboard_engagement.json"
SCHEMA_VERSION = 1
RETENTION_DAYS = 400
CHECKPOINT_HOURS = (24, 168)
WINDOW_HOURS = 6
MIN_COMPARISON_POSTS = 30
ENGAGEMENT_FIELDS = (
    ("likes", "likeCount"),
    ("replies", "replyCount"),
    ("reposts", "repostCount"),
    ("quotes", "quoteCount"),
    ("bookmarks", "bookmarkCount"),
)


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Engagement observation timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def load(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def engagement(post: dict) -> dict[str, int]:
    return {
        name: max(0, int(post.get(api_name) or 0))
        for name, api_name in ENGAGEMENT_FIELDS
    }


def _saved_observation(
    checkpoint: str, observation: dict, created: datetime, now: datetime
) -> dict:
    if checkpoint not in {"24", "168"}:
        raise ValueError("Unsupported engagement checkpoint")
    status = observation["status"]
    if status not in {"observed", "missed", "before_coverage"}:
        raise ValueError("Unsupported engagement observation status")
    validated = {"status": status}
    if status == "observed":
        observed = _time(observation["observed_at"])
        age = (observed - created).total_seconds() / 3600
        if (
            observed > now
            or not int(checkpoint) <= age < int(checkpoint) + WINDOW_HOURS
        ):
            raise ValueError("Engagement observation falls outside its age band")
        counts = observation["engagement"]
        if set(counts) != {name for name, _ in ENGAGEMENT_FIELDS} or any(
            type(value) is not int or value < 0 for value in counts.values()
        ):
            raise ValueError("Invalid engagement observation counts")
        validated.update(observed_at=observed.isoformat(), engagement=dict(counts))
    return validated


def _saved_checkpoints(item: dict, now: datetime) -> dict:
    created = _time(item["created_at"])
    if created > now:
        raise ValueError("A published joke cannot have a future publication time")
    checkpoints = item["checkpoints"]
    if not isinstance(checkpoints, dict):
        raise ValueError("Dashboard engagement checkpoints must be an object")
    return {
        checkpoint: _saved_observation(checkpoint, observation, created, now)
        for checkpoint, observation in checkpoints.items()
    }


def _initial_records(existing: dict | None, now: datetime) -> tuple[datetime, dict]:
    if existing is None:
        return now, {}
    if existing.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported dashboard engagement state schema version")
    if not isinstance(existing.get("posts"), list):
        raise ValueError("Dashboard engagement posts must be a list")
    started = _time(existing["coverage_started_at"])
    if started > now:
        raise ValueError("Dashboard engagement coverage cannot start in the future")
    records = {}
    for item in existing["posts"]:
        created = _time(item["created_at"])
        if created < now - timedelta(days=RETENTION_DAYS):
            continue
        records[item["uri"]] = {
            "uri": item["uri"],
            "created_at": created.isoformat(),
            "provider": item["provider"],
            "checkpoints": _saved_checkpoints(item, now),
        }
    return started, records


def _observe(
    created: datetime, hours: int, started: datetime, post: dict | None, now: datetime
) -> dict | None:
    due = created + timedelta(hours=hours)
    deadline = due + timedelta(hours=WINDOW_HOURS)
    if deadline <= started:
        return {"status": "before_coverage"}
    observed = (
        _time(post.get("_dashboard_observed_at", now.isoformat()))
        if post is not None
        else now
    )
    if post is not None and due <= observed < deadline:
        return {
            "status": "observed",
            "observed_at": observed.isoformat(),
            "engagement": engagement(post),
        }
    if max(now, observed) >= deadline:
        return {"status": "missed"}
    return None


def _publication_record(
    entry: dict, post: dict | None, started: datetime, now: datetime
) -> dict | None:
    created_at = (post or {}).get("record", {}).get("createdAt")
    created = (
        _time(created_at)
        if created_at
        else datetime.fromtimestamp(entry["ts"], timezone.utc)
    )
    if created + timedelta(
        hours=max(CHECKPOINT_HOURS) + WINDOW_HOURS
    ) <= started or created < now - timedelta(days=RETENTION_DAYS):
        return None
    if created > now:
        raise ValueError("A published joke cannot have a future publication time")
    return {
        "uri": entry["post_uri"],
        "created_at": created.isoformat(),
        "provider": entry.get("provider") or "unknown",
        "checkpoints": {},
    }


def collect(
    existing: dict | None,
    publications: list[dict],
    visible_posts: list[dict],
    now: datetime,
) -> dict:
    started, records = _initial_records(existing, now)
    visible = {post["uri"]: post for post in visible_posts}
    for entry in publications:
        uri = entry.get("post_uri")
        if not uri or uri in records:
            continue
        record = _publication_record(entry, visible.get(uri), started, now)
        if record is not None:
            records[uri] = record
    for uri, record in records.items():
        created = _time(record["created_at"])
        for hours in CHECKPOINT_HOURS:
            key = str(hours)
            if key in record["checkpoints"]:
                continue
            observation = _observe(created, hours, started, visible.get(uri), now)
            if observation is not None:
                record["checkpoints"][key] = observation
    return {
        "schema_version": SCHEMA_VERSION,
        "coverage_started_at": started.isoformat(),
        "retention_days": RETENTION_DAYS,
        "posts": sorted(
            records.values(), key=lambda item: (item["created_at"], item["uri"])
        ),
    }


def _statistics(records: list[dict], hours: int) -> dict:
    observations = [
        item["checkpoints"][str(hours)]
        for item in records
        if item["checkpoints"].get(str(hours), {}).get("status") == "observed"
    ]
    totals = [sum(item["engagement"].values()) for item in observations]
    breakdown = {
        name: sum(item["engagement"][name] for item in observations)
        for name, _ in ENGAGEMENT_FIELDS
    }
    statuses = Counter(
        item["checkpoints"].get(str(hours), {}).get("status", "pending")
        for item in records
    )
    return {
        "tracked": len(records),
        "observed": len(observations),
        "missed": statuses["missed"],
        "pending": statuses["pending"],
        "before_coverage": statuses["before_coverage"],
        "mean": round(sum(totals) / len(totals), 3) if totals else None,
        "median": median(totals) if totals else None,
        "zero_share": round(totals.count(0) * 100 / len(totals), 2) if totals else None,
        "engagement": breakdown,
    }


def _groups(records: list[dict], hours: int, field: str) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for record in records:
        value = (
            record["provider"]
            if field == "provider"
            else f"{_time(record['created_at']).hour:02d}:00"
        )
        grouped.setdefault(value, []).append(record)
    return [
        {field: value, **_statistics(items, hours)}
        for value, items in sorted(grouped.items())
    ]


def summary(receipts: dict, visible_posts: list[dict], now: datetime) -> dict:
    records = receipts["posts"]
    visible = {post["uri"]: post for post in visible_posts}
    checkpoints = {}
    for hours in CHECKPOINT_HOURS:
        end = (now - timedelta(hours=hours + WINDOW_HOURS)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        periods = {}
        recent = []
        for name, stop in (("recent", end), ("previous", end - timedelta(days=30))):
            start = stop - timedelta(days=30)
            selected = [
                item for item in records if start <= _time(item["created_at"]) < stop
            ]
            periods[name] = {
                "start": start.date().isoformat(),
                "end": stop.date().isoformat(),
                **_statistics(selected, hours),
            }
            if name == "recent":
                recent = selected
        months: dict[str, list[dict]] = {}
        for record in records:
            if _time(record["created_at"]) < end:
                months.setdefault(record["created_at"][:7], []).append(record)
        ranked = sorted(
            (
                item
                for item in recent
                if item["uri"] in visible
                and item["checkpoints"].get(str(hours), {}).get("status") == "observed"
            ),
            key=lambda item, checkpoint=str(hours): sum(
                item["checkpoints"][checkpoint]["engagement"].values()
            ),
            reverse=True,
        )[:6]
        top_posts = []
        for item in ranked:
            observation = item["checkpoints"][str(hours)]
            top_posts.append(
                {
                    "uri": item["uri"],
                    "created_at": item["created_at"],
                    "text": str(
                        visible[item["uri"]].get("record", {}).get("text") or ""
                    ),
                    "observed_at": observation["observed_at"],
                    "age_hours": (
                        (
                            _time(observation["observed_at"])
                            - _time(item["created_at"])
                        ).total_seconds()
                        / 3600
                    ),
                    "engagement": observation["engagement"],
                }
            )
        checkpoints[str(hours)] = {
            "window_hours": [hours, hours + WINDOW_HOURS],
            "coverage": _statistics(records, hours),
            "periods": periods,
            "months": [
                {"month": month, **_statistics(items, hours)}
                for month, items in sorted(months.items())
            ],
            "providers": _groups(recent, hours, "provider"),
            "publishing_hours": _groups(recent, hours, "utc_hour"),
            "top_posts": top_posts,
        }
    return {
        "coverage_started_at": receipts["coverage_started_at"],
        "retention_days": RETENTION_DAYS,
        "comparison_min_posts": MIN_COMPARISON_POSTS,
        "checkpoints": checkpoints,
    }
