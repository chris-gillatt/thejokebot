### File: bluesky_follower_utils.py
def fetch_paginated_data(client_method, actor, limit=100, max_pages=100):
    """Fetch paginated data (followers or following) with guardrails."""
    data = []
    cursor = None
    pages = 0
    seen_cursors = set()

    while pages < max_pages:
        if cursor is not None:
            if cursor in seen_cursors:
                print("Repeated pagination cursor detected; stopping early.")
                break
            seen_cursors.add(cursor)

        pages += 1
        try:
            response = client_method(actor=actor, cursor=cursor, limit=limit)
        except Exception as exc:
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
