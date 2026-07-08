import base64
import html
import os
import random
import time

import requests
import atproto_client.exceptions
import regex

import bluesky_denylist
import bluesky_config
import bluesky_joke_providers
import bluesky_state
from bluesky_common import login_client

# Joke memory and posting defaults now come from central runtime config.
_POSTING_CONFIG = bluesky_config.get_posting_config()
DAYS_LIMIT = _POSTING_CONFIG["days_limit"]
MAX_ATTEMPTS = _POSTING_CONFIG["max_attempts"]
BLUESKY_MAX_POST_CHARS = _POSTING_CONFIG["max_post_chars"]
DEFAULT_POSTING_HASHTAGS = _POSTING_CONFIG["hashtags"]

# Bluesky character limits are based on user-visible characters, not code points.
_GRAPHEME_PATTERN = regex.compile(r"\X")


def _grapheme_len(text: str) -> int:
    """Return grapheme-cluster count for user-visible character length checks."""
    return len(_GRAPHEME_PATTERN.findall(text))


_MOJIBAKE_MARKERS = ("Ã", "Â", "â", "ð", "\x80", "\x99")
_HTML_UNESCAPE_PASSES = 3
_DEDUPE_NORMALISATION_PATTERN = regex.compile(r"[\p{P}\s_]+")


def get_max_joke_chars(hashtags: list[str]) -> int:
    """Return maximum grapheme length available for joke text with selected hashtags."""
    hashtag_suffix_len = 2 + _grapheme_len(" ".join(hashtags))
    return BLUESKY_MAX_POST_CHARS - hashtag_suffix_len


def get_posting_hashtag_pool() -> list[str]:
    """Return the resolved posting tag pool from central runtime tag resolution."""
    return list(bluesky_config.get_posting_tag_runtime_config()["tag_pool"])


def _build_group_lookup(similarity_groups: list[list[str]]) -> dict[str, int]:
    """Map each lowercased tag (without #) to its similarity group index."""
    lookup: dict[str, int] = {}
    for gi, group in enumerate(similarity_groups):
        for tag in group:
            lookup[tag.lower()] = gi
    return lookup


def shuffle_posting_hashtags(
    hashtag_pool: list[str],
    offset: int,
    similarity_groups: list[list[str]],
) -> list[str]:
    """Return the pool shuffled by seed=offset with at most one tag per similarity group."""
    if not hashtag_pool:
        return []

    group_lookup = _build_group_lookup(similarity_groups)
    pool_copy = list(hashtag_pool)
    random.Random(offset).shuffle(pool_copy)

    result = []
    seen_groups: set[int] = set()
    for tag in pool_copy:
        tag_key = tag.lstrip("#").lower()
        group_id = group_lookup.get(tag_key)
        if group_id is not None:
            if group_id in seen_groups:
                continue
            seen_groups.add(group_id)
        result.append(tag)

    return result


def fit_hashtags_to_joke(
    joke_text: str,
    shuffled_pool: list[str],
    tag_default: str,
    tag_fallback: str,
    max_count: int,
    similarity_groups: list[list[str]],
) -> list[str]:
    """
    Select up to max_count whole hashtags that fit within the post character limit.

    Decision tree:
    - If tag_default fits alongside the joke: start with [tag_default] and greedily
      add tags from shuffled_pool up to max_count, skipping group-duplicates.
    - If tag_default does not fit: return [tag_fallback] (last resort).

    Minimum 1 tag. Never returns a partial tag.
    """
    max_chars = BLUESKY_MAX_POST_CHARS
    joke_graphemes = _grapheme_len(joke_text)

    def _post_len(tags: list[str]) -> int:
        return joke_graphemes + 2 + _grapheme_len(" ".join(tags))

    if _post_len([tag_default]) > max_chars:
        return [tag_fallback]

    group_lookup = _build_group_lookup(similarity_groups)
    selected = [tag_default]
    seen_groups: set[int] = set()
    default_key = tag_default.lstrip("#").lower()
    if default_key in group_lookup:
        seen_groups.add(group_lookup[default_key])

    skip = {tag_default.lower(), tag_fallback.lower()}

    for candidate in shuffled_pool:
        if len(selected) >= max_count:
            break
        if candidate.lower() in skip:
            continue
        candidate_key = candidate.lstrip("#").lower()
        group_id = group_lookup.get(candidate_key)
        if group_id is not None and group_id in seen_groups:
            continue
        if _post_len(selected + [candidate]) <= max_chars:
            selected.append(candidate)
            skip.add(candidate.lower())
            if group_id is not None:
                seen_groups.add(group_id)

    return selected


def get_fallback_joke():
    """Return a static self-deprecating joke when all providers are exhausted."""
    fallback_jokes = [
        "Why did this script fail? Because it has too much byte and not enough bark.",
        "If this script were a programmer, it would still be debugging hello world.",
        "Looks like this script is throwing exceptions faster than I throw tantrums.",
    ]
    return random.choice(fallback_jokes)


def get_current_epoch():
    return int(time.time())


def sanitise_joke_text(joke: str) -> str:
    """Repair common mojibake and normalise quote punctuation for posting."""
    cleaned = joke.replace("\r\n", "\n").replace("\r", "\n").strip()
    cleaned = cleaned.lstrip("\ufeff")

    # Decode HTML entities from provider payloads (for example, '&#039;').
    # Use bounded passes so doubly escaped forms like '&amp;#039;' are fixed.
    for _ in range(_HTML_UNESCAPE_PASSES):
        unescaped = html.unescape(cleaned)
        if unescaped == cleaned:
            break
        cleaned = unescaped

    # Repair common UTF-8 text that was accidentally decoded as Latin-1.
    if any(marker in cleaned for marker in _MOJIBAKE_MARKERS):
        try:
            repaired = cleaned.encode("latin-1").decode("utf-8")
            if sum(cleaned.count(m) for m in _MOJIBAKE_MARKERS) > sum(
                repaired.count(m) for m in _MOJIBAKE_MARKERS
            ):
                cleaned = repaired
        except UnicodeError:
            pass

    # Prefer plain ASCII quotes to avoid display quirks across clients/providers.
    cleaned = (
        cleaned.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )
    return cleaned


def _normalise_joke_for_deduplication(joke: str) -> str:
    """Return a case-folded duplicate key with punctuation, spaces, and underscores removed."""
    return _DEDUPE_NORMALISATION_PATTERN.sub("", joke.casefold())


def _encode_deduplication_key(joke: str) -> str:
    """Encode the duplicate-check normal form as base64 for set membership."""
    normalised = _normalise_joke_for_deduplication(joke)
    return base64.b64encode(normalised.encode("utf-8")).decode()


def _normalise_stored_b64_for_deduplication(encoded_joke: str) -> str:
    """Normalise a stored joke b64 value for duplicate checks."""
    try:
        decoded = base64.b64decode(encoded_joke, validate=True).decode("utf-8")
    except (ValueError, UnicodeError):
        return ""
    return _encode_deduplication_key(decoded)


def pick_joke(
    recent_b64s: set, provider_name: str, hashtags: list[str] | None = None
) -> tuple:
    """
    Fetch up to MAX_ATTEMPTS jokes from provider_name, skipping recent duplicates
    and jokes that would exceed the Bluesky post character limit once hashtags
    are appended.
    Returns (joke_text, b64_encoded) on success, raises ValueError if all attempts
    are duplicates, too long, or the provider raises.
    """
    fetch_fn = bluesky_joke_providers.PROVIDERS[provider_name]
    selected_hashtags = hashtags or DEFAULT_POSTING_HASHTAGS
    max_joke_chars = get_max_joke_chars(selected_hashtags)
    recent_dedupe_b64s = {
        _normalise_stored_b64_for_deduplication(encoded) for encoded in recent_b64s
    }
    for _ in range(MAX_ATTEMPTS):
        joke = sanitise_joke_text(fetch_fn())
        grapheme_count = _grapheme_len(joke)
        if grapheme_count > max_joke_chars:
            print(
                f"Skipping joke from '{provider_name}': "
                f"{grapheme_count} graphemes exceeds limit of {max_joke_chars}"
            )
            continue
        encoded = base64.b64encode(joke.encode("utf-8")).decode()
        dedupe_encoded = _encode_deduplication_key(joke)
        if dedupe_encoded not in recent_dedupe_b64s:
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
        facets.append(
            {
                "index": {
                    "byteStart": tag_start,
                    "byteEnd": tag_end,
                },
                "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": tag[1:]}],
            }
        )
        current_offset = tag_end + 1

    return facets


def main():
    state = bluesky_state.load_state()
    cutoff = get_current_epoch() - (DAYS_LIMIT * 86400)

    tag_runtime = bluesky_config.get_posting_tag_runtime_config()
    tag_fallback = tag_runtime["tag_fallback"]
    tag_default = tag_runtime["tag_default"]
    tag_max_count = tag_runtime["tag_max_count"]
    tag_similarity_groups = tag_runtime["tag_similarity_groups"]
    posting_hashtag_pool = tag_runtime["tag_pool"]
    tag_pool_source = tag_runtime["tag_pool_source"]

    tag_offset = bluesky_state.get_posting_tag_offset(state)
    shuffled_pool = shuffle_posting_hashtags(
        posting_hashtag_pool, tag_offset, tag_similarity_groups
    )
    print(
        f"Posting tag pool source: {tag_pool_source} ({len(posting_hashtag_pool)} tags)"
    )

    recent_b64s = bluesky_state.get_recent_b64s(state, cutoff)
    denylist_payload = bluesky_denylist.load_denylist()
    recent_b64s |= bluesky_denylist.get_denylisted_b64s(denylist_payload)

    # Determine provider order: explicit override or next primary provider in
    # alternating rotation, followed by remaining primaries, then backups,
    # and finally the fallback jokebook.
    provider_override = os.getenv("BLUESKY_JOKE_PROVIDER", "").strip().lower() or None
    if provider_override in bluesky_joke_providers.PROVIDERS:
        providers_to_try = [provider_override]
    else:
        selected = bluesky_state.get_next_provider(state)
        primary_providers = list(bluesky_joke_providers.PRIMARY_PROVIDERS)
        backup_providers = list(bluesky_joke_providers.BACKUP_PROVIDERS)
        fallback_provider = bluesky_joke_providers.FALLBACK_PROVIDER
        providers_to_try = [selected]
        providers_to_try += [p for p in primary_providers if p != selected]
        providers_to_try += backup_providers
        providers_to_try += [fallback_provider]

    joke = None
    b64 = None
    used_provider = None

    for provider_name in providers_to_try:
        try:
            joke, b64 = pick_joke(recent_b64s, provider_name, hashtags=[tag_fallback])
            used_provider = provider_name
            break
        except (
            ValueError,
            requests.RequestException,
            TimeoutError,
            atproto_client.exceptions.NetworkError,
        ) as e:
            print(f"Provider '{provider_name}' failed: {e}")
            bluesky_state.record_failure(state, provider_name, str(e))

    if not joke:
        joke = get_fallback_joke()
        b64 = base64.b64encode(joke.encode("utf-8")).decode()
        used_provider = "fallback"

    # Advance rotation after a successful provider fetch (regardless of post outcome).
    if used_provider != "fallback":
        bluesky_state.record_provider_used(state, used_provider)

    hashtags_for_post = fit_hashtags_to_joke(
        joke,
        shuffled_pool,
        tag_default,
        tag_fallback,
        tag_max_count,
        tag_similarity_groups,
    )
    hashtags_string = " ".join(hashtags_for_post)
    joke_with_tags = f"{joke}\n\n{hashtags_string}"
    facets = build_hashtag_facets(joke, hashtags_for_post)

    try:
        client, _ = login_client()
        handle = getattr(client.me, "handle", "")
        display_identity = f"@{handle}" if handle else "@unknown"
        print(
            f"Posting as {display_identity} via '{used_provider}': {repr(joke_with_tags)}"
        )
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
        bluesky_state.advance_posting_tag_offset(
            state,
            1,
            len(posting_hashtag_pool),
        )
    except (
        ValueError,
        requests.RequestException,
        TimeoutError,
        atproto_client.exceptions.NetworkError,
    ) as e:
        print(f"Failed to post joke: {e}")
    finally:
        bluesky_state.prune_old_jokes(state, cutoff)
        bluesky_state.save_state(state)


if __name__ == "__main__":
    main()
