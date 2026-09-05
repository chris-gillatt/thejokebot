import time
from bluesky_common import retry_network_call


class IncompletePaginationError(RuntimeError):
    """Raised when a caller requires a complete graph but pagination stops early."""


def _handle_incomplete_pagination(message, require_complete):
    if require_complete:
        raise IncompletePaginationError(message)
    print(f"{message}; stopping early.")


def _extract_page_items(response):
    """Return the items list from a paginated follower/following response, or None."""
    if hasattr(response, "followers"):
        return response.followers
    if hasattr(response, "follows"):
        return response.follows
    return None


def _pagination_guard_message(cursor, seen_cursors, started_at, max_runtime_seconds):
    if time.monotonic() - started_at >= max_runtime_seconds:
        return f"Reached pagination runtime safety limit ({max_runtime_seconds}s)"
    if cursor is not None and cursor in seen_cursors:
        return "Repeated pagination cursor detected"
    return None


def _normalise_page(response, cursor):
    next_cursor = getattr(response, "cursor", None)
    if cursor is not None and next_cursor == cursor:
        return None, next_cursor, "Repeated pagination cursor detected"
    items = _extract_page_items(response)
    if items is None:
        return None, next_cursor, "Unexpected paginated response format"
    return items, next_cursor, None


def fetch_paginated_data(
    client_method,
    actor,
    limit=100,
    max_pages=100,
    max_runtime_seconds=30,
    require_complete=False,
):
    """Fetch paginated data (followers or following) with guardrails."""
    data = []
    cursor = None
    next_cursor = None
    pages = 0
    seen_cursors = set()
    started_at = time.monotonic()

    while pages < max_pages:
        message = _pagination_guard_message(
            cursor, seen_cursors, started_at, max_runtime_seconds
        )
        if message:
            _handle_incomplete_pagination(message, require_complete)
            break

        if cursor is not None:
            seen_cursors.add(cursor)

        pages += 1
        response = retry_network_call(
            lambda: client_method(actor=actor, cursor=cursor, limit=limit),
            description=f"fetching paginated data page {pages}",
        )

        items, next_cursor, message = _normalise_page(response, cursor)
        if message:
            _handle_incomplete_pagination(message, require_complete)
            break
        assert items is not None
        data.extend(items)

        if not next_cursor:
            break
        cursor = next_cursor

    if pages >= max_pages and next_cursor:
        message = f"Reached pagination safety limit ({max_pages} pages)"
        _handle_incomplete_pagination(message, require_complete)

    return data


def extract_list_member_did(item) -> str:
    """Extract a DID from a getList item payload."""
    subject = getattr(item, "subject", None)
    if subject is None and isinstance(item, dict):
        subject = item.get("subject")

    if isinstance(subject, str) and subject.startswith("did:"):
        return subject.strip()

    did = getattr(subject, "did", None)
    if did is None and isinstance(subject, dict):
        did = subject.get("did")

    return str(did or "").strip()


def _normalise_list_page(response):
    items = getattr(response, "items", None)
    cursor = getattr(response, "cursor", None)
    if isinstance(response, dict):
        items = response.get("items", []) if items is None else items
        cursor = response.get("cursor") if cursor is None else cursor
    return items, cursor


def _add_list_member_dids(dids, items):
    for item in items:
        did = extract_list_member_did(item)
        if did:
            dids.add(did)


def fetch_list_member_dids(
    client,
    list_uri: str,
    description: str = "fetching source list members",
) -> set[str]:
    """Return all DIDs from a Bluesky list URI."""
    dids: set[str] = set()
    cursor = None

    while True:
        params = {"list": list_uri, "limit": 100}
        if cursor:
            params["cursor"] = cursor

        resp = retry_network_call(
            lambda: client.app.bsky.graph.get_list(params),
            description=description,
        )

        items, cursor = _normalise_list_page(resp)
        if not isinstance(items, (list, tuple, set)):
            print("Unexpected list-member response format; stopping early.")
            break

        _add_list_member_dids(dids, items)
        if not cursor:
            break

    return dids
