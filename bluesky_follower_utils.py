### File: bluesky_follower_utils.py
def fetch_paginated_data(client_method, actor):
    """Fetch paginated data (followers or following)."""
    data = []
    cursor = None
    while True:
        response = client_method(actor=actor, cursor=cursor)
        if hasattr(response, 'followers'):
            data.extend(response.followers)  # For followers
        elif hasattr(response, 'follows'):
            data.extend(response.follows)  # For follows
        cursor = getattr(response, 'cursor', None)
        if not cursor:
            break
    return data
