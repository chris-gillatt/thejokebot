import time
from thejokebot.runtime import retry_network_call


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
            lambda current_cursor=cursor: client_method(
                actor=actor, cursor=current_cursor, limit=limit
            ),
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
    if isinstance(response, dict):
        items = response.get("items")
        cursor = response.get("cursor")
        list_view = response.get("list")
    else:
        items = getattr(response, "items", None)
        cursor = getattr(response, "cursor", None)
        list_view = getattr(response, "list", None)

    if isinstance(list_view, dict):
        response_list_uri = list_view.get("uri")
    else:
        response_list_uri = getattr(list_view, "uri", None)
    return items, cursor, response_list_uri


def _check_list_runtime(started_at, max_runtime_seconds):
    if time.monotonic() - started_at >= max_runtime_seconds:
        raise IncompletePaginationError(
            f"Reached list pagination runtime safety limit ({max_runtime_seconds}s)"
        )


def _fetch_list_page(
    client, list_uri, cursor, page, description, started_at, max_runtime_seconds
):
    _check_list_runtime(started_at, max_runtime_seconds)
    params = {"list": list_uri, "limit": 100}
    if cursor:
        params["cursor"] = cursor

    response = retry_network_call(
        lambda current_params=params: client.app.bsky.graph.get_list(current_params),
        description=f"{description} page {page}",
    )
    _check_list_runtime(started_at, max_runtime_seconds)
    return _normalise_list_page(response)


def _validate_list_page(items, response_list_uri, list_uri):
    if response_list_uri != list_uri:
        raise IncompletePaginationError("List response URI mismatch")
    if not isinstance(items, (list, tuple, set)):
        raise IncompletePaginationError("Unexpected list-member response format")

    page_dids = set()
    for item in items:
        did = extract_list_member_did(item)
        if not did.startswith("did:"):
            raise IncompletePaginationError(
                "List response contains a member without a valid DID"
            )
        page_dids.add(did)
    return page_dids


def _validate_next_list_cursor(cursor, seen_cursors):
    if cursor is None or cursor == "":
        return None
    if not isinstance(cursor, str) or not cursor.strip():
        raise IncompletePaginationError("Invalid list pagination cursor")
    if cursor in seen_cursors:
        raise IncompletePaginationError("Repeated list pagination cursor detected")
    return cursor


def fetch_list_member_dids(
    client,
    list_uri: str,
    description: str = "fetching source list members",
    max_pages: int = 100,
    max_runtime_seconds: float = 30,
) -> set[str]:
    """Return all DIDs from a completely and consistently read Bluesky list."""
    if not isinstance(list_uri, str) or not list_uri.startswith("at://"):
        raise IncompletePaginationError("Invalid source list URI")
    if max_pages < 1 or max_runtime_seconds <= 0:
        raise ValueError("List pagination limits must be positive")

    dids: set[str] = set()
    cursor = None
    seen_cursors = set()
    started_at = time.monotonic()

    for page in range(1, max_pages + 1):
        items, next_cursor, response_list_uri = _fetch_list_page(
            client,
            list_uri,
            cursor,
            page,
            description,
            started_at,
            max_runtime_seconds,
        )
        dids.update(_validate_list_page(items, response_list_uri, list_uri))
        cursor = _validate_next_list_cursor(next_cursor, seen_cursors)
        if cursor is None:
            return dids
        seen_cursors.add(cursor)

    raise IncompletePaginationError(
        f"Reached list pagination safety limit ({max_pages} pages)"
    )
