"""Allowlisted public candidate-supply counters."""

from __future__ import annotations

import re

FIELDS = (
    "fetches",
    "candidates",
    "selected",
    "published",
    "duplicate",
    "too_long",
    "network_error",
    "provider_error",
    "exhausted",
)


def _validated_counts(record: dict) -> dict:
    counts = {field: record[field] for field in FIELDS}
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise ValueError("Provider telemetry counters must be non-negative integers")
    if (
        counts["candidates"]
        != counts["duplicate"] + counts["too_long"] + counts["selected"]
        or counts["fetches"]
        != counts["candidates"] + counts["network_error"] + counts["provider_error"]
        or counts["published"] > counts["selected"]
        or counts["selected"] > 1
        or counts["exhausted"] > 1
        or (counts["exhausted"] and counts["selected"])
    ):
        raise ValueError("Provider telemetry counters do not reconcile")
    return counts


def sanitise(records: list) -> list[dict]:
    if not isinstance(records, list):
        raise ValueError("Provider candidate telemetry must be a list")
    clean = []
    seen = set()
    for record in records:
        if not isinstance(record, dict) or not {"name", *FIELDS} <= record.keys():
            raise ValueError("Provider telemetry record is missing required fields")
        name = record["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9_-]{1,64}", name):
            raise ValueError("Invalid provider telemetry name")
        if name in seen:
            raise ValueError("Duplicate provider telemetry record")
        seen.add(name)
        clean.append({"name": name, **_validated_counts(record)})
    return clean
