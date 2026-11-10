"""Maintain the bot's configured Bluesky account blocks."""

import hashlib
import os
import re
import time
from datetime import datetime, timezone

from atproto import models
from atproto_client.exceptions import BadRequestError

from thejokebot.runtime import get_nested_value, mask_sensitive, retry_network_call

BLOCK_DIDS_ENV = "BLUESKY_BLOCK_DIDS"
_BLOCK_COLLECTION = "app.bsky.graph.block"
_TID_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"
_DID_PATTERN = re.compile(
    r"^did:[a-z0-9]+:(?:[A-Za-z0-9._-]|%[0-9A-Fa-f]{2})+"
    r"(?::(?:[A-Za-z0-9._-]|%[0-9A-Fa-f]{2})+)*$"
)


def _block_rkey(repo_did: str, did: str) -> str:
    digest = hashlib.sha256(f"{repo_did}:{did}".encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)
    encoded = ["2"] * 13
    for index in range(12, -1, -1):
        value, digit = divmod(value, len(_TID_ALPHABET))
        encoded[index] = _TID_ALPHABET[digit]
    return "".join(encoded)


def _block_record_at_key(client, repo_did: str, rkey: str):
    try:
        return retry_network_call(
            lambda: client.com.atproto.repo.get_record(
                {"repo": repo_did, "collection": _BLOCK_COLLECTION, "rkey": rkey}
            ),
            description="reconciling configured block",
        )
    except BadRequestError as exc:
        if (
            get_nested_value(exc, "response", "status_code") == 400
            and get_nested_value(exc, "response", "content", "error")
            == "RecordNotFound"
        ):
            return None
        raise


def _verify_block_record(receipt, repo_did: str, did: str, rkey: str) -> None:
    expected_uri = f"at://{repo_did}/{_BLOCK_COLLECTION}/{rkey}"
    if get_nested_value(receipt, "uri") != expected_uri:
        raise ValueError("Block record receipt does not match its saved key")
    value = get_nested_value(receipt, "value")
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        value = model_dump(by_alias=True, exclude_none=True)
    if not isinstance(value, dict):
        raise ValueError("Block record receipt has no record value")
    if value.get("$type") != _BLOCK_COLLECTION or value.get("subject") != did:
        raise ValueError("Block record receipt does not match its saved subject")


def _verify_block_response(response, repo_did: str, rkey: str) -> None:
    expected_uri = f"at://{repo_did}/{_BLOCK_COLLECTION}/{rkey}"
    if get_nested_value(response, "uri") != expected_uri or not get_nested_value(
        response, "cid"
    ):
        raise ValueError("Block create receipt does not match its saved key")


def _create_or_reconcile_block(client, repo_did: str, did: str, record) -> None:
    rkey = _block_rkey(repo_did, did)
    existing = _block_record_at_key(client, repo_did, rkey)
    if existing is not None:
        _verify_block_record(existing, repo_did, did, rkey)
        return

    try:
        response = client.app.bsky.graph.block.create(
            repo=repo_did,
            record=record,
            rkey=rkey,
        )
    except Exception as create_error:
        try:
            existing = _block_record_at_key(client, repo_did, rkey)
        except Exception:
            raise create_error
        if existing is None:
            raise
        _verify_block_record(existing, repo_did, did, rkey)
    else:
        _verify_block_response(response, repo_did, rkey)


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
            _create_or_reconcile_block(client, account_did, did, record)
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
