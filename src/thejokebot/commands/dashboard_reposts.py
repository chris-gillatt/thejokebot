"""Aggregate observed repost inventory without publishing private review records."""

from collections import Counter
from datetime import datetime, timedelta

from thejokebot.repost_reviews import UNCERTAIN_STATUSES, timestamp, utc_now


def _window(entries: list[dict], now: datetime, days: int | None) -> dict:
    selected = [
        entry
        for entry in entries
        if timestamp(entry["created_at"]) <= now
        and (
            days is None or timestamp(entry["created_at"]) >= now - timedelta(days=days)
        )
    ]
    authors: dict[str, dict] = {}
    daily = Counter()
    for entry in selected:
        author = authors.setdefault(
            entry["author_did"], {"handle": entry["handle"], "count": 0}
        )
        author["count"] += 1
        if entry["handle"]:
            author["handle"] = entry["handle"]
        daily[timestamp(entry["created_at"]).date().isoformat()] += 1
    total = len(selected)
    ranked = [
        {**author, "share": author["count"] / total} for author in authors.values()
    ]
    ranked.sort(key=lambda author: (-author["count"], author["handle"] or ""))
    dates = []
    start = (
        now.date() - timedelta(days=days)
        if days
        else (
            timestamp(min(entry["created_at"] for entry in selected)).date()
            if selected
            else None
        )
    )
    while start is not None and start <= now.date():
        day = start.isoformat()
        dates.append({"date": day, "count": daily[day]})
        start += timedelta(days=1)
    return {
        "total": total,
        "distinct_authors": len(authors),
        "text": sum(entry["kind"] == "text" for entry in selected),
        "image": sum(entry["kind"] == "image" for entry in selected),
        "unknown_format": sum(
            entry["kind"] not in ("text", "image") for entry in selected
        ),
        "replies": sum(entry["is_reply"] is True for entry in selected),
        "unknown_reply": sum(entry["is_reply"] is None for entry in selected),
        "authors": ranked,
        "daily": dates,
    }


def collect(state: dict, now: datetime) -> dict:
    now = utc_now(now)
    reviews = state.get("repost_reviews", {})
    inventory = reviews.get("inventory")
    candidates = list(reviews.get("candidates", {}).values())
    return {
        "collected_at": inventory["collected_at"] if inventory else None,
        "coverage": "Current retained reposts only; removed/deleted history and manual/automated provenance are not reconstructed.",
        "confirmed_publications": sum(
            bool(entry.get("published_at")) for entry in candidates
        ),
        "confirmed_removals": sum(
            bool(entry.get("removed_at")) for entry in candidates
        ),
        "pending_reviews": sum(
            entry["status"] == "proposed"
            and bool(entry.get("issue_id"))
            and timestamp(entry["expires_at"]) > now
            for entry in candidates
        ),
        "uncertain_outcomes": sum(
            entry["status"] in UNCERTAIN_STATUSES for entry in candidates
        ),
        "windows": {
            str(days) if days else "all": _window(
                inventory["entries"], timestamp(inventory["collected_at"]), days
            )
            for days in (7, 30, None)
        }
        if inventory
        else {},
    }
