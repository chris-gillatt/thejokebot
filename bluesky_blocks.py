"""Maintain the bot's configured Bluesky account blocks."""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone

from atproto import models

from bluesky_common import mask_sensitive, retry_network_call

BLOCK_DIDS_ENV = "BLUESKY_BLOCK_DIDS"
_DID_PATTERN = re.compile(
    r"^did:[a-z0-9]+:(?:[A-Za-z0-9._-]|%[0-9A-Fa-f]{2})+"
    r"(?::(?:[A-Za-z0-9._-]|%[0-9A-Fa-f]{2})+)*$"
)


def parse_block_dids(raw_value: str) -> set[str]:
    """Parse comma/newline-separated DIDs, allowing trailing handle comments."""
    dids: set[str] = set()
    invalid: list[str] = []

    for raw_entry in re.split(r"[\n,]", raw_value or ""):
        did = raw_entry.split("#", 1)[0].strip()
        if not did:
            continue
        if not _DID_PATTERN.fullmatch(did):
            invalid.append(mask_sensitive(did))
            continue
        dids.add(did)

    if invalid:
        raise ValueError(
            f"{BLOCK_DIDS_ENV} contains invalid DID entries: {', '.join(invalid)}"
        )

    return dids


def _get_value(value, name, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def fetch_blocked_dids(client) -> set[str]:
    """Return a complete snapshot of DIDs currently blocked by the account."""
    blocked_dids: set[str] = set()
    cursor = None

    while True:
        response = retry_network_call(
            lambda current_cursor=cursor: client.app.bsky.graph.get_blocks(
                params={"cursor": current_cursor, "limit": 100}
            ),
            description="listing current account blocks",
        )
        for profile in _get_value(response, "blocks", []) or []:
            did = _get_value(profile, "did")
            if did:
                blocked_dids.add(did)

        cursor = _get_value(response, "cursor")
        if not cursor:
            return blocked_dids


def reconcile_blocks(
    client,
    desired_dids: set[str],
    *,
    dry_run: bool,
    action_delay_seconds: float,
) -> int:
    """Create missing configured blocks and return the number requiring action."""
    if not desired_dids:
        return 0

    account_did = client.me.did
    if account_did in desired_dids:
        raise ValueError(f"{BLOCK_DIDS_ENV} must not contain the bot account DID.")

    blocked_dids = fetch_blocked_dids(client)
    missing_dids = sorted(desired_dids - blocked_dids)

    for index, did in enumerate(missing_dids, start=1):
        masked_did = mask_sensitive(did)
        if dry_run:
            print(f"[DRY-RUN] Would block {masked_did}")
        else:
            record = models.AppBskyGraphBlock.Record(
                subject=did,
                created_at=datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
            )
            retry_network_call(
                lambda current_record=record: client.app.bsky.graph.block.create(
                    repo=account_did,
                    record=current_record,
                ),
                description=f"blocking configured account {masked_did}",
            )
            print(f"Blocked configured account {masked_did}")

        if action_delay_seconds > 0 and index < len(missing_dids):
            time.sleep(action_delay_seconds)

    return len(missing_dids)


def reconcile_configured_blocks(
    client,
    *,
    dry_run: bool,
    action_delay_seconds: float,
) -> int:
    """Load the private block policy from the environment and enforce it."""
    desired_dids = parse_block_dids(os.getenv(BLOCK_DIDS_ENV, ""))
    return reconcile_blocks(
        client,
        desired_dids,
        dry_run=dry_run,
        action_delay_seconds=action_delay_seconds,
    )
