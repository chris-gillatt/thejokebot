import base64
import os
import random
import time

import requests
import atproto_client.exceptions

import bluesky_denylist
import bluesky_joke_providers
import bluesky_state
from bluesky_common import login_client

DAYS_LIMIT = 90
MAX_ATTEMPTS = 5
BLUESKY_MAX_POST_CHARS = 300

# Hashtags
HASHTAGS = ["#jokes", "#dadjoke", "#funny"]

# Graphemes consumed by "\n\n" + space-joined hashtags appended to every post.
_HASHTAG_SUFFIX_LEN = 2 + len(" ".join(HASHTAGS))  # 2 newlines + tag string
_MAX_JOKE_CHARS = BLUESKY_MAX_POST_CHARS - _HASHTAG_SUFFIX_LEN


def get_fallback_joke():
    """Return a static self-deprecating joke when all providers are exhausted."""
    fallback_jokes = [
        "Why did this script fail? Because it has too much byte and not enough bark.",
        "If this script were a programmer, it would still be debugging hello world.",
        "Looks like this script is throwing exceptions faster than I throw tantrums."
    ]
    return random.choice(fallback_jokes)


def get_current_epoch():
    return int(time.time())


def pick_joke(recent_b64s: set, provider_name: str) -> tuple:
    """
    Fetch up to MAX_ATTEMPTS jokes from provider_name, skipping recent duplicates
    and jokes that would exceed the Bluesky post character limit once hashtags
    are appended.
    Returns (joke_text, b64_encoded) on success, raises ValueError if all attempts
    are duplicates, too long, or the provider raises.
    """
    fetch_fn = bluesky_joke_providers.PROVIDERS[provider_name]
    for _ in range(MAX_ATTEMPTS):
        joke = fetch_fn()
        if len(joke) > _MAX_JOKE_CHARS:
            print(
                f"Skipping joke from '{provider_name}': "
                f"{len(joke)} chars exceeds limit of {_MAX_JOKE_CHARS}"
            )
            continue
        encoded = base64.b64encode(joke.encode("utf-8")).decode()
        if encoded not in recent_b64s:
            return joke, encoded
    raise ValueError(
        f"All {MAX_ATTEMPTS} jokes from '{provider_name}' were recent duplicates or too long"
    )


def build_hashtag_facets(joke_text, hashtags):
    facets = []
    current_offset = len(joke_text.encode("UTF-8")) + 2

    for tag in hashtags:
        tag_bytes = tag.encode("UTF-8")
        tag_start = current_offset
        tag_end = tag_start + len(tag_bytes)
        facets.append({
            "index": {
                "byteStart": tag_start,
                "byteEnd": tag_end,
            },
            "features": [
                {"$type": "app.bsky.richtext.facet#tag", "tag": tag[1:]}
            ],
        })
        current_offset = tag_end + 1

    return facets


def main():
    state = bluesky_state.load_state()
    cutoff = get_current_epoch() - (DAYS_LIMIT * 86400)
    recent_b64s = bluesky_state.get_recent_b64s(state, cutoff)
    denylist_payload = bluesky_denylist.load_denylist()
    recent_b64s |= bluesky_denylist.get_denylisted_b64s(denylist_payload)

    # Determine provider order: explicit override or next primary provider in
    # alternating rotation, followed by remaining primaries and then backups.
    provider_override = os.getenv("BLUESKY_JOKE_PROVIDER", "").strip().lower() or None
    if provider_override in bluesky_joke_providers.PROVIDERS:
        providers_to_try = [provider_override]
    else:
        selected = bluesky_state.get_next_provider(state)
        primary_providers = list(bluesky_joke_providers.PRIMARY_PROVIDERS)
        backup_providers = list(bluesky_joke_providers.BACKUP_PROVIDERS)
        providers_to_try = [selected]
        providers_to_try += [p for p in primary_providers if p != selected]
        providers_to_try += backup_providers

    joke = None
    b64 = None
    used_provider = None

    for provider_name in providers_to_try:
        try:
            joke, b64 = pick_joke(recent_b64s, provider_name)
            used_provider = provider_name
            break
        except (ValueError, requests.RequestException, TimeoutError, atproto_client.exceptions.NetworkError) as e:
            print(f"Provider '{provider_name}' failed: {e}")
            bluesky_state.record_failure(state, provider_name, str(e))

    if not joke:
        joke = get_fallback_joke()
        b64 = base64.b64encode(joke.encode("utf-8")).decode()
        used_provider = "fallback"

    # Advance rotation after a successful provider fetch (regardless of post outcome).
    if used_provider != "fallback":
        bluesky_state.record_provider_used(state, used_provider)

    hashtags_string = " ".join(HASHTAGS)
    joke_with_tags = f"{joke}\n\n{hashtags_string}"
    facets = build_hashtag_facets(joke, HASHTAGS)

    try:
        client, _ = login_client()
        handle = getattr(client.me, "handle", "")
        display_identity = f"@{handle}" if handle else "@unknown"
        print(f"Posting as {display_identity} via '{used_provider}': {repr(joke_with_tags)}")
        post = client.send_post(text=joke_with_tags, facets=facets)
        print("Joke successfully posted!")

        post_uri = getattr(post, "uri", None)
        post_cid = getattr(post, "cid", None)
        if isinstance(post, dict):
            post_uri = post.get("uri")
            post_cid = post.get("cid")

        bluesky_state.add_posted_joke(
            state,
            b64,
            used_provider,
            post_uri=post_uri,
            post_cid=post_cid,
        )
    except (ValueError, requests.RequestException, TimeoutError, atproto_client.exceptions.NetworkError) as e:
        print(f"Failed to post joke: {e}")
    finally:
        bluesky_state.prune_old_jokes(state, cutoff)
        bluesky_state.save_state(state)


if __name__ == "__main__":
    main()
