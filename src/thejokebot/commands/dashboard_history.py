"""Dashboard history storage domain for metrics collection."""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from thejokebot import state as bot_state
from thejokebot.paths import DASHBOARD_DIR

_UTC_OFFSET = "+00:00"
METRICS_FILE = DASHBOARD_DIR / "data" / "metrics.json"
HISTORY_DIR = METRICS_FILE.parent / "history"
SCHEMA_VERSION = 11
HISTORY_SCHEMA_VERSION = 1
WORKFLOW_WINDOW_DAYS = 30
TRACKED_WORKFLOWS = {
    "bluesky_dashboard",
    "bluesky_follow_fellows",
    "bluesky_follows_and_likes",
    "bluesky_manage_starter_pack",
    "bluesky_post_joke",
    "bluesky_process_reports",
    "bluesky_unfollow",
    "bluesky_validate_unfollow_ignore",
    "codeql",
    "pr_auto_merge",
    "provider_health_check",
    "python_tests",
    "ruff_quality",
    "validate_runtime_config",
}
HISTORY_RECORD_FIELDS = {
    "account_observations": (
        "period_start",
        "collected_at",
        "followers",
        "following",
        "profile_posts",
        "joke_posts",
        "engagement",
        "engagement_total",
    ),
    "activity_runs": (
        "id",
        "attempt",
        "workflow",
        "created_at",
        "follows",
        "unfollows",
        "selected",
        "failed",
        "eligible",
        "processed",
        "missing_uri",
        "stopped_early",
        "social_summary_observed",
        "follow_back_candidates",
        "follow_back_added",
        "interaction_candidates",
        "interaction_eligible",
        "interaction_added",
        "interactions_liked",
        "joke_replies",
        "starter_pack_follows",
        "starter_pack_scan_complete",
        "protected",
        "proposals",
        "acknowledgements",
        "approved_removals",
        "unresolved",
        "provider_attempts",
        "starting_provider",
        "successful_source",
        "fallthrough",
        "static_fallback",
        "duplicate",
        "too_long",
        "network_error",
        "provider_error",
        "posted",
    ),
    "automation_runs": (
        "id",
        "attempt",
        "workflow",
        "created_at",
        "updated_at",
        "status",
        "conclusion",
    ),
    "daily_activity": ("date", "joke_posts", "follows", "unfollows"),
    "operational_observations": (
        "period_start",
        "collected_at",
        "providers",
        "posting_delivery",
        "network_maintenance",
        "audience_growth",
        "starter_pack_attribution",
    ),
}


def _period_start(now: datetime) -> str:
    bucket_hour = now.hour - (now.hour % 6)
    return now.replace(hour=bucket_hour, minute=0, second=0, microsecond=0).isoformat()


def _utc_month(value: str) -> str:
    timestamp = datetime.fromisoformat(value.replace("Z", _UTC_OFFSET))
    if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
        raise ValueError("Dashboard history timestamps must use UTC")
    return timestamp.strftime("%Y-%m")


def _empty_history_partition(month: str) -> dict:
    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "month": month,
        **{family: [] for family in HISTORY_RECORD_FIELDS},
    }


def _history_record(record: dict, family: str) -> dict:
    return {
        field: record[field]
        for field in HISTORY_RECORD_FIELDS[family]
        if field in record
    }


def _history_identity(item: dict, family: str):
    if family in {"account_observations", "operational_observations"}:
        return item["period_start"]
    if family in {"activity_runs", "automation_runs"}:
        return (
            item["workflow"],
            int(item["id"]),
            int(item.get("attempt") or 1),
        )
    return item["date"]


def _history_sort_key(item: dict, family: str):
    if family in {"activity_runs", "automation_runs"}:
        return (
            item["created_at"],
            item["workflow"],
            int(item["id"]),
            int(item.get("attempt") or 1),
        )
    return _history_identity(item, family)


def _merge_history_records(partition: dict, family: str, records: list[dict]) -> None:
    if family == "activity_runs":
        authoritative = {
            (int(item["id"]), int(item.get("attempt") or 1))
            for item in [*partition[family], *records]
            if item["workflow"] != "legacy_activity"
        }
        partition[family] = [
            item
            for item in partition[family]
            if item["workflow"] != "legacy_activity"
            or (int(item["id"]), int(item.get("attempt") or 1)) not in authoritative
        ]
        records = [
            item
            for item in records
            if item["workflow"] != "legacy_activity"
            or (int(item["id"]), int(item.get("attempt") or 1)) not in authoritative
        ]
    merged = {_history_identity(item, family): item for item in partition[family]}
    merged.update((_history_identity(item, family), item) for item in records)
    partition[family] = sorted(
        merged.values(), key=lambda item: _history_sort_key(item, family)
    )


def _migrate_existing_history(existing: dict | None) -> dict[str, dict]:
    partitions: dict[str, dict] = {}

    def merge(month: str, family: str, record: dict) -> None:
        partition = partitions.setdefault(month, _empty_history_partition(month))
        _merge_history_records(partition, family, [_history_record(record, family)])

    for snapshot in (existing or {}).get("snapshots", []):
        if snapshot.get("source") != "bluesky_snapshot":
            continue
        merge(_utc_month(snapshot["period_start"]), "account_observations", snapshot)
    for run in (existing or {}).get("workflow_activity", {}).get("runs", []):
        migrated_run = {**run, "workflow": run.get("workflow") or "legacy_activity"}
        merge(_utc_month(run["created_at"]), "activity_runs", migrated_run)
    for activity in (existing or {}).get("daily_activity", []):
        month = activity["date"][:7]
        datetime.strptime(activity["date"], "%Y-%m-%d")
        merge(month, "daily_activity", activity)
    return dict(sorted(partitions.items()))


def _history_from_collection(
    metrics: dict, workflow_runs: list[dict]
) -> dict[str, dict]:
    partitions = _migrate_existing_history(metrics)

    def merge(month: str, family: str, record: dict) -> None:
        partition = partitions.setdefault(month, _empty_history_partition(month))
        _merge_history_records(partition, family, [_history_record(record, family)])

    for run in workflow_runs:
        workflow = str(run.get("name") or "")
        if (
            workflow not in TRACKED_WORKFLOWS
            or run.get("id") is None
            or not run.get("created_at")
        ):
            continue
        record = {
            "id": int(run["id"]),
            "attempt": int(run.get("run_attempt") or 1),
            "workflow": workflow,
            "created_at": run["created_at"],
            "updated_at": run.get("updated_at"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
        }
        merge(_utc_month(record["created_at"]), "automation_runs", record)

    providers = []
    for provider in metrics.get("providers", {}).get("providers", []):
        providers.append(
            {
                field: provider.get(field)
                for field in (
                    "name",
                    "published",
                    "visible_posts",
                    "average_interactions",
                    "fallthroughs",
                    "rejection_counts",
                    "healthy",
                    "configured",
                    "last_health_check_at",
                    "consecutive_health_failures",
                )
            }
        )
    delivery = metrics.get("posting_delivery", {})
    network = metrics.get("network_maintenance", {})
    audience_growth = metrics.get("audience_growth", {})
    starter_packs = metrics.get("starter_pack_attribution", {})
    operational = {
        "period_start": _period_start(
            datetime.fromisoformat(metrics["generated_at"].replace("Z", _UTC_OFFSET))
        ),
        "collected_at": metrics["generated_at"],
        "providers": providers,
        "posting_delivery": {
            "current_streak": delivery.get("current_streak"),
            "windows": delivery.get("windows", {}),
        },
        "network_maintenance": {
            "window_days": network.get("window_days"),
            "response_window": network.get("response_window", {}),
            "unfollow": {
                field: network.get("unfollow", {}).get(field)
                for field in (
                    "completed_runs",
                    "eligible",
                    "processed",
                    "unfollowed",
                    "failed",
                    "missing_records",
                    "cap_remaining",
                    "stopped_early_runs",
                )
            },
        },
        "audience_growth": {
            "window_days": audience_growth.get("window_days"),
            "net_followers": {
                window: audience_growth.get("net_followers", {}).get(window)
                for window in ("7", "30")
            },
            "sources": {
                source: {
                    field: audience_growth.get("sources", {}).get(source, {}).get(field)
                    for field in (
                        "denominator",
                        "considered",
                        "acquired",
                        "success_rate",
                    )
                }
                for source in bot_state.ACQUISITION_COHORT_SOURCES
            },
            "cohorts": {
                "checkpoint_days": audience_growth.get("cohorts", {}).get(
                    "checkpoint_days", []
                ),
                "coverage_started_at": audience_growth.get("cohorts", {}).get(
                    "coverage_started_at"
                ),
                "periods": copy.deepcopy(
                    audience_growth.get("cohorts", {}).get("periods", [])
                ),
            },
            "coverage": {
                field: audience_growth.get("coverage", {}).get(field)
                for field in ("social_started_at", "discovery_started_at")
            },
        },
        "starter_pack_attribution": {
            "window_days": starter_packs.get("window_days"),
            "coverage_started_at": starter_packs.get("coverage_started_at"),
            "last_checked_at": starter_packs.get("last_checked_at"),
            "total_follows": starter_packs.get("total_follows"),
            "windows": {
                window: starter_packs.get("windows", {}).get(window)
                for window in ("7", "30")
            },
            "packs": [
                {
                    field: pack.get(field)
                    for field in (
                        "name",
                        "creator_handle",
                        "url",
                        "follows",
                        "windows",
                        "share_30_day",
                    )
                }
                for pack in starter_packs.get("packs", [])
            ],
        },
    }
    merge(
        _utc_month(operational["period_start"]),
        "operational_observations",
        operational,
    )
    return dict(sorted(partitions.items()))


def _history_record_months_and_identities(records: list[dict], family: str):
    if family in {"account_observations", "operational_observations"}:
        return (
            [_utc_month(item["period_start"]) for item in records],
            [item["period_start"] for item in records],
        )
    if family in {"activity_runs", "automation_runs"}:
        return (
            [_utc_month(item["created_at"]) for item in records],
            [
                (item["workflow"], int(item["id"]), int(item.get("attempt") or 1))
                for item in records
            ],
        )
    return ([item["date"][:7] for item in records], [item["date"] for item in records])


def _validate_history_records(records, family: str, expected_month: str) -> None:
    if not isinstance(records, list):
        raise ValueError(f"Dashboard history {family} must be a list")
    months, identities = _history_record_months_and_identities(records, family)
    if any(month != expected_month for month in months):
        raise ValueError("Dashboard history record is in the wrong month")
    if len(identities) != len(set(identities)):
        raise ValueError(f"Dashboard history {family} contains duplicates")
    if records != sorted(records, key=lambda item: _history_sort_key(item, family)):
        raise ValueError(f"Dashboard history {family} is not sorted")


def _validate_history_partition(partition: dict, expected_month: str) -> None:
    if partition.get("schema_version") != HISTORY_SCHEMA_VERSION:
        raise ValueError("Unsupported dashboard history schema version")
    if partition.get("month") != expected_month:
        raise ValueError("Dashboard history partition month does not match its path")
    for family in HISTORY_RECORD_FIELDS:
        records = partition.get(family)
        _validate_history_records(records, family, expected_month)


def _load_history_partitions(history_dir: Path = HISTORY_DIR) -> dict[str, dict]:
    partitions = {}
    if not history_dir.exists():
        return partitions
    for path in sorted(history_dir.glob("[0-9][0-9][0-9][0-9]/[0-9][0-9].json")):
        month = f"{path.parent.name}-{path.stem}"
        with path.open(encoding="utf-8") as history_file:
            partition = json.load(history_file)
        _validate_history_partition(partition, month)
        partitions[month] = partition
    return partitions


def _merge_history_partitions(
    existing: dict[str, dict], incoming: dict[str, dict]
) -> dict[str, dict]:
    partitions = copy.deepcopy(existing)
    for month, incoming_partition in incoming.items():
        partition = partitions.setdefault(month, _empty_history_partition(month))
        _merge_history_partition(partition, incoming_partition, month)
    return dict(sorted(partitions.items()))


def _merge_history_partition(partition: dict, incoming: dict, month: str) -> None:
    for family in HISTORY_RECORD_FIELDS:
        _merge_history_records(partition, family, incoming[family])
    _validate_history_partition(partition, month)


def _merge_history_daily_partition(
    partition: dict,
    cutoff,
    final_observations: dict,
    activity_by_date: dict,
) -> None:
    for observation in partition["account_observations"]:
        collected = datetime.fromisoformat(
            observation["collected_at"].replace("Z", _UTC_OFFSET)
        )
        if collected.date() >= cutoff:
            continue
        current = final_observations.get(collected.date())
        if current is None or observation["collected_at"] > current["collected_at"]:
            final_observations[collected.date()] = observation
    for activity in partition["daily_activity"]:
        activity_date = datetime.strptime(activity["date"], "%Y-%m-%d").date()
        if activity_date < cutoff:
            activity_by_date[activity_date] = activity


def _history_daily(partitions: dict[str, dict], now: datetime) -> dict:
    cutoff = (now - timedelta(days=WORKFLOW_WINDOW_DAYS)).date()
    final_observations = {}
    activity_by_date = {}
    for partition in partitions.values():
        _merge_history_daily_partition(
            partition, cutoff, final_observations, activity_by_date
        )
    snapshots = [
        {**observation, "source": "bluesky_daily"}
        for _, observation in sorted(final_observations.items())
    ]
    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "snapshots": snapshots,
        "daily_activity": [
            activity for _, activity in sorted(activity_by_date.items())
        ],
    }


def _history_index(partitions: dict[str, dict], generated_at: str) -> dict:
    months = []
    for month, partition in partitions.items():
        timestamps = [
            item["period_start"] for item in partition["account_observations"]
        ] + [item["created_at"] for item in partition["activity_runs"]]
        timestamps.extend(
            f"{item['date']}T00:00:00Z" for item in partition["daily_activity"]
        )
        months.append(
            {
                "month": month,
                "path": f"{month[:4]}/{month[5:]}.json",
                "counts": {
                    family: len(partition[family]) for family in HISTORY_RECORD_FIELDS
                },
                "first_timestamp": min(timestamps) if timestamps else None,
                "last_timestamp": max(timestamps) if timestamps else None,
            }
        )
    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "generated_at": generated_at,
        "months": months,
    }


def _write_json(path: Path, payload: dict) -> None:
    serialised = json.dumps(payload, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == serialised:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(serialised, encoding="utf-8")
    os.replace(temporary_path, path)


def _write_history(
    partitions: dict[str, dict],
    now: datetime,
    workflow_activity: dict | None = None,
    history_dir: Path = HISTORY_DIR,
) -> None:
    for month, partition in partitions.items():
        _validate_history_partition(partition, month)
        _write_json(history_dir / month[:4] / f"{month[5:]}.json", partition)
    _write_json(history_dir / "index.json", _history_index(partitions, now.isoformat()))
    _write_json(history_dir / "daily.json", _history_daily(partitions, now))
    _write_json(
        history_dir / "collector.json",
        {
            "schema_version": HISTORY_SCHEMA_VERSION,
            "coverage_start": (workflow_activity or {}).get("coverage_start"),
            "expired_before": (workflow_activity or {}).get("expired_before"),
        },
    )


def _collector_existing(
    existing: dict | None,
    partitions: dict[str, dict],
    now: datetime,
    history_dir: Path = HISTORY_DIR,
) -> dict:
    cutoff = now - timedelta(days=WORKFLOW_WINDOW_DAYS)
    observations = [
        {**item, "source": "bluesky_snapshot"}
        for partition in partitions.values()
        for item in partition["account_observations"]
    ]
    earlier = [
        item
        for item in observations
        if datetime.fromisoformat(item["collected_at"].replace("Z", _UTC_OFFSET))
        < cutoff
    ]
    recent = [
        item
        for item in observations
        if datetime.fromisoformat(item["collected_at"].replace("Z", _UTC_OFFSET))
        >= cutoff
    ]
    snapshots = ([earlier[-1]] if earlier else []) + recent
    runs = [
        item
        for partition in partitions.values()
        for item in partition["activity_runs"]
        if datetime.fromisoformat(item["created_at"].replace("Z", _UTC_OFFSET))
        >= cutoff
    ]
    metadata = (existing or {}).get("workflow_activity", {})
    collector_path = history_dir / "collector.json"
    if collector_path.exists():
        with collector_path.open(encoding="utf-8") as collector_file:
            stored_metadata = json.load(collector_file)
        if stored_metadata.get("schema_version") != HISTORY_SCHEMA_VERSION:
            raise ValueError("Unsupported dashboard history collector schema version")
        metadata = stored_metadata
    return {
        "schema_version": SCHEMA_VERSION,
        "snapshots": snapshots,
        "workflow_activity": {
            "window_days": WORKFLOW_WINDOW_DAYS,
            "coverage_start": metadata.get("coverage_start") or cutoff.isoformat(),
            "expired_before": metadata.get("expired_before"),
            "runs": sorted(runs, key=lambda item: item["created_at"]),
        },
    }


def _compact_metrics(metrics: dict, now: datetime) -> dict:
    cutoff = now - timedelta(days=WORKFLOW_WINDOW_DAYS)
    compact = dict(metrics)
    compact["snapshots"] = [
        item
        for item in metrics["snapshots"]
        if datetime.fromisoformat(item["collected_at"].replace("Z", _UTC_OFFSET))
        >= cutoff
    ]
    compact["daily_activity"] = [
        item
        for item in metrics["daily_activity"]
        if datetime.strptime(item["date"], "%Y-%m-%d").date() >= cutoff.date()
    ]
    compact.pop("workflow_activity", None)
    return compact
