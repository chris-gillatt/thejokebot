"""Read bounded discovery candidates from the account's saved custom feeds."""

from atproto import models

from thejokebot.runtime import get_nested_value, retry_network_call

MAX_SAVED_FEEDS = 10


def saved_feed_uris(preferences) -> list[str]:
    """Prefer current preferences; never resurrect feeds removed from V2."""
    current = [
        pref
        for pref in preferences
        if isinstance(pref, models.AppBskyActorDefs.SavedFeedsPrefV2)
    ]
    if current:
        candidates = [
            item.value for pref in current for item in pref.items if item.type == "feed"
        ]
    else:
        candidates = [
            uri
            for pref in preferences
            if isinstance(pref, models.AppBskyActorDefs.SavedFeedsPref)
            for uri in pref.saved
        ]
    return list(dict.fromkeys(candidates))


def eligible_author_dids(authors) -> list[str]:
    dids = []
    for author in authors:
        viewer = get_nested_value(author, "viewer")
        if any(
            get_nested_value(viewer, flag)
            for flag in ("blocking", "blocked_by", "muted")
        ):
            continue
        dids.append(author.did)
    return dids


def fetch_saved_feed_users(
    client, *, limit: int, offset: int = 0
) -> tuple[dict[str, list[str]], int]:
    """Sample one page per feed, allowing read errors to stop discovery before writes."""
    preferences = retry_network_call(
        client.app.bsky.actor.get_preferences,
        description="reading saved-feed preferences",
    ).preferences
    feeds = saved_feed_uris(preferences)
    if not feeds:
        return {}, 0
    offset %= len(feeds)
    if len(feeds) > MAX_SAVED_FEEDS:
        print(
            f"Saved-feed discovery sampling {MAX_SAVED_FEEDS} of {len(feeds)} custom feeds "
            f"from offset {offset}."
        )
    candidates = {}
    rotated_feeds = feeds[offset:] + feeds[:offset]
    for index, uri in enumerate(rotated_feeds[:MAX_SAVED_FEEDS], start=1):
        response = retry_network_call(
            lambda feed_uri=uri: client.app.bsky.feed.get_feed(
                {"feed": feed_uri, "limit": limit}
            ),
            description=f"reading saved feed {index}",
        )
        candidates[f"feed:{index}"] = eligible_author_dids(
            item.post.author for item in response.feed
        )
    next_offset = (offset + min(len(feeds), MAX_SAVED_FEEDS)) % len(feeds)
    return candidates, next_offset
