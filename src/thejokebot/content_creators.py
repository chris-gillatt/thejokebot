"""Discover and retain creators whose content the account likes or reposts."""

import re
import time

from thejokebot import state_transactions
from thejokebot.followers import IncompletePaginationError
from thejokebot.runtime import get_nested_value, retry_network_call

_COLLECTIONS = ("app.bsky.feed.like", "app.bsky.feed.repost")
_CONTENT_URI = re.compile(
    r"at://(did:[a-z0-9]+:[^/\s?#]+)/app\.bsky\.feed\.(post|repost|generator)/[^/\s?#]+"
)
_MAX_PAGES = 100
_MAX_RUNTIME_SECONDS = 120


def get_protected_dids(state: dict) -> set[str]:
    """Return permanent creator protections, rejecting malformed saved data."""
    dids = state.get("follow_tracking", {}).get("content_creator_dids", [])
    if not isinstance(dids, list) or any(
        not isinstance(did, str)
        or not _CONTENT_URI.fullmatch(f"at://{did}/app.bsky.feed.post/key")
        for did in dids
    ):
        raise ValueError("Invalid saved content-creator protections")
    return set(dids)


def _record_creators(state: dict, dids: set[str]) -> None:
    protected = get_protected_dids(state) | dids
    state.setdefault("follow_tracking", {})["content_creator_dids"] = sorted(protected)


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise IncompletePaginationError("Content-creator scan runtime limit reached")


def _record_creator(record, repo_did: str, collection: str) -> str | None:
    uri = get_nested_value(record, "uri")
    prefix = f"at://{repo_did}/{collection}/"
    if (
        not isinstance(uri, str)
        or not uri.startswith(prefix)
        or not re.fullmatch(r"[A-Za-z0-9._~:-]+", uri[len(prefix) :])
    ):
        raise ValueError(
            "Content interaction record belongs to an unexpected repository"
        )
    value = get_nested_value(record, "value")
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        value = model_dump(by_alias=True, exclude_none=True)
    if not isinstance(value, dict) or value.get("$type") != collection:
        raise ValueError("Content interaction record has an unexpected type")
    subject_uri = get_nested_value(value, "subject", "uri")
    match = (
        _CONTENT_URI.fullmatch(subject_uri) if isinstance(subject_uri, str) else None
    )
    if match is None or (
        match.group(2) == "generator" and collection != "app.bsky.feed.like"
    ):
        raise ValueError("Content interaction has no canonical content subject URI")
    if match.group(2) == "generator":
        print("Skipped custom-feed like during content-creator scan.")
        return None
    return match.group(1)


def _scan_collection(
    client, repo_did: str, collection: str, deadline: float
) -> set[str]:
    dids: set[str] = set()
    cursor = None
    seen_cursors: set[str] = set()
    for page in range(_MAX_PAGES):
        params = {"repo": repo_did, "collection": collection, "limit": 100}
        if cursor:
            params["cursor"] = cursor

        def fetch_page():
            _check_deadline(deadline)
            return client.com.atproto.repo.list_records(params)

        response = retry_network_call(
            fetch_page, description=f"reading content interactions page {page + 1}"
        )
        _check_deadline(deadline)
        records = get_nested_value(response, "records")
        if not isinstance(records, list):
            raise IncompletePaginationError("Unexpected content interaction page")
        for record in records:
            did = _record_creator(record, repo_did, collection)
            if did is not None and did != repo_did:
                dids.add(did)
        cursor = get_nested_value(response, "cursor")
        if cursor is None or cursor == "":
            return dids
        if not isinstance(cursor, str) or not cursor.strip() or cursor in seen_cursors:
            raise IncompletePaginationError(
                "Invalid or repeated content interaction cursor"
            )
        seen_cursors.add(cursor)
    raise IncompletePaginationError("Content-creator scan page limit reached")


def sync_protections(client, state: dict, dry_run: bool) -> set[str]:
    """Read both complete collections before checkpointing permanent protections."""
    get_protected_dids(state)
    repo_did = client.me.did
    deadline = time.monotonic() + _MAX_RUNTIME_SECONDS
    dids: set[str] = set()
    for collection in _COLLECTIONS:
        dids.update(_scan_collection(client, repo_did, collection, deadline))

    def record(latest):
        _record_creators(latest, dids)

    if dry_run:
        record(state)
    else:
        state_transactions.apply(state, record)
    return get_protected_dids(state)
