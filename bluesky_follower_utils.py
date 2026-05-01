import time
import requests
import atproto_client.exceptions
from bluesky_common import retry_network_call


def fetch_paginated_data(
    client_method,
    actor,
    limit=100,
    max_pages=100,
    max_runtime_seconds=30,
):
    """Fetch paginated data (followers or following) with guardrails."""
    data = []
    cursor = None
    pages = 0
    seen_cursors = set()
    started_at = time.monotonic()

    while pages < max_pages:
        if time.monotonic() - started_at >= max_runtime_seconds:
            print(
                f"Reached pagination runtime safety limit ({max_runtime_seconds}s); stopping early."
            )
            break

        if cursor is not None:
            if cursor in seen_cursors:
                print("Repeated pagination cursor detected; stopping early.")
                break
            seen_cursors.add(cursor)

        pages += 1
        try:
            response = retry_network_call(
                lambda: client_method(actor=actor, cursor=cursor, limit=limit),
                description=f"fetching paginated data page {pages}",
            )
        except (requests.RequestException, TimeoutError, atproto_client.exceptions.NetworkError) as exc:
            print(f"Failed to fetch paginated data on page {pages}: {exc}")
            break

        next_cursor = getattr(response, "cursor", None)
        if cursor is not None and next_cursor == cursor:
            print("Repeated pagination cursor detected; stopping early.")
            break

        if hasattr(response, "followers"):
            data.extend(response.followers)
        elif hasattr(response, "follows"):
            data.extend(response.follows)
        else:
            print("Unexpected paginated response format; stopping early.")
            break

        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor

    if pages >= max_pages:
        print(f"Reached pagination safety limit ({max_pages} pages).")

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

        items = getattr(resp, "items", None)
        if items is None and isinstance(resp, dict):
            items = resp.get("items", [])
        if not isinstance(items, (list, tuple, set)):
            print("Unexpected list-member response format; stopping early.")
            break

        for item in items or []:
            did = extract_list_member_did(item)
            if did:
                dids.add(did)

        cursor = getattr(resp, "cursor", None)
        if cursor is None and isinstance(resp, dict):
            cursor = resp.get("cursor")
        if not cursor:
            break

    return dids
