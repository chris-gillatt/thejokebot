"""
Joke provider functions for the joke bot.

Each provider is a callable with signature () -> str that returns a single
joke string (plain text, may contain newlines for two-part jokes) or raises
an exception if the joke cannot be fetched.

Primary providers participate in normal alternating rotation. Backup providers
are only tried after the primaries fail, unless explicitly selected via
BLUESKY_JOKE_PROVIDER for local testing or emergency use.
"""

import base64
import json
import os
import pathlib
import random

import requests
import bluesky_state

JOKE_TIMEOUT_SECONDS = 15

_USER_AGENT = "thejokebot (https://github.com/chris-gillatt/thejokebot)"
_ICANHAZDADJOKE_URL = "https://icanhazdadjoke.com"
_API_NINJAS_DADJOKES_URL = "https://api.api-ninjas.com/v1/dadjokes"
_SYRSLY_DAD_URL = "https://www.syrsly.com/joke/dad"

# Safe categories only — Dark is excluded intentionally.
# safe-mode is embedded in the URL as a value-less parameter because requests
# drops params with None values and encodes empty strings as key=.
_JOKEAPI_URL = (
    "https://v2.jokeapi.dev/joke/Misc,Programming,Pun,Spooky,Christmas?safe-mode"
)
_JOKEAPI_BLACKLIST = "nsfw,explicit,racist,sexist"
_GROANDECK_URL = "https://groandeck.com/api/v1/random"


# Provider configuration: three-tier fallback system
#
# PRIMARY PROVIDERS (normal rotation):
# Single source of truth for primary-provider rotation order lives in
# bluesky_state.PROVIDER_ROTATION_ORDER. These three providers form the
# active rotation and should all be called equally often.
PRIMARY_PROVIDERS = list(bluesky_state.PROVIDER_ROTATION_ORDER)

# BACKUP PROVIDERS (emergency fallback):
# Only tried after all primaries fail. Used when providers are temporarily
# down or rate-limited. Syrsly is preferred (family-friendly), followed by
# API Ninjas (requires API key), and finally the bundled jokebook.
BACKUP_PROVIDERS = ["syrsly", "api_ninjas"]

# FALLBACK PROVIDER (last resort, always available):
# Bundled offline joke list. Requires no network or API key. Should always
# succeed, making it the final safety net in the provider chain.
FALLBACK_PROVIDER = "jokebot_jokebook"

_JOKEBOOK_PATH = pathlib.Path(__file__).parent / "resources" / "jokebot_jokebook.json"


def fetch_from_icanhazdadjoke(timeout: int = JOKE_TIMEOUT_SECONDS) -> str:
    """Fetch a random dad joke from icanhazdadjoke.com."""
    resp = requests.get(
        _ICANHAZDADJOKE_URL,
        headers={"Accept": "text/plain", "User-Agent": _USER_AGENT},
        timeout=timeout,
    )
    resp.raise_for_status()
    joke = resp.text.strip()
    if not joke:
        raise ValueError("icanhazdadjoke returned an empty response")
    return joke


def fetch_from_jokeapi(timeout: int = JOKE_TIMEOUT_SECONDS) -> str:
    """
    Fetch a family-friendly joke from v2.jokeapi.dev.

    Uses safe-mode and blacklists nsfw/explicit/racist/sexist flags.
    Two-part jokes (setup + delivery) are joined with a blank line so they
    read naturally as a Bluesky post.
    """
    resp = requests.get(
        _JOKEAPI_URL,
        params={"blacklistFlags": _JOKEAPI_BLACKLIST, "lang": "en"},
        headers={"User-Agent": _USER_AGENT},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("error"):
        raise ValueError(f"JokeAPI error: {data.get('message', 'unknown')}")

    if data.get("type") == "twopart":
        setup = data.get("setup", "").strip()
        delivery = data.get("delivery", "").strip()
        if not setup or not delivery:
            raise ValueError("JokeAPI returned an incomplete two-part joke")
        return f"{setup}\n\n{delivery}"

    joke = data.get("joke", "").strip()
    if not joke:
        raise ValueError("JokeAPI returned an empty joke")
    return joke


def fetch_from_groandeck(timeout: int = JOKE_TIMEOUT_SECONDS) -> str:
    """
    Fetch a random pun or wordplay joke from GroanDeck.

    Free tier; no API key required. Response shape is
    ``{"setup": "...", "punchline": "..."}`` — always two-part.
    All GroanDeck categories are family-friendly (puns, animals, food, etc.);
    no adult or dark-humour content is present in the pool.
    """
    resp = requests.get(
        _GROANDECK_URL,
        headers={"User-Agent": _USER_AGENT},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()

    setup = data.get("setup", "").strip()
    punchline = data.get("punchline", "").strip()
    if not setup or not punchline:
        raise ValueError("GroanDeck returned an incomplete joke")
    return f"{setup}\n\n{punchline}"


def fetch_from_syrsly(timeout: int = JOKE_TIMEOUT_SECONDS) -> str:
    """
    Fetch a random dad joke from Syrsly's jokes API.

    Uses the Syrsly dad-joke endpoint to stay aligned with family-friendly
    expectations. The API returns plain text and may include encoded entities;
    final normalisation happens in bluesky_post_joke.sanitise_joke_text().
    """
    resp = requests.get(
        _SYRSLY_DAD_URL,
        headers={"User-Agent": _USER_AGENT},
        timeout=timeout,
    )
    resp.raise_for_status()
    joke = resp.text.strip()
    if not joke:
        raise ValueError("Syrsly returned an empty response")
    return joke


def fetch_from_api_ninjas(timeout: int = JOKE_TIMEOUT_SECONDS) -> str:
    """
    Fetch a dad joke from API Ninjas.

    This provider requires API_NINJAS_API_KEY and is intended as a last-resort
    live provider because the API has a very limited joke pool.
    """
    api_key = os.getenv("API_NINJAS_API_KEY", "").strip()
    if not api_key:
        raise ValueError("API_NINJAS_API_KEY is not set")

    resp = requests.get(
        _API_NINJAS_DADJOKES_URL,
        headers={"User-Agent": _USER_AGENT, "X-Api-Key": api_key},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()

    if not isinstance(data, list) or not data:
        raise ValueError("API Ninjas returned an unexpected response shape")

    joke = data[0].get("joke", "").strip()
    if not joke:
        raise ValueError("API Ninjas returned an empty joke")
    return joke


def fetch_from_jokebot_jokebook() -> str:
    """
    Pick a random joke from the bundled offline joke list.

    Jokes are stored in resources/jokebot_jokebook.json as base64-encoded strings
    (same encoding as posted_jokes in the state file).  This provider requires
    no network access or API key and should always succeed, making it the last
    resort in the backup chain.
    """
    if not _JOKEBOOK_PATH.exists():
        raise RuntimeError(f"Jokebook file not found at {_JOKEBOOK_PATH}")
    with open(_JOKEBOOK_PATH, encoding="utf-8") as f:
        data = json.load(f)
    jokes = data.get("jokes", [])
    if not jokes:
        raise ValueError("Jokebook file is empty")
    encoded = random.choice(jokes)
    return base64.b64decode(encoded).decode()


# Registry for all available providers.
PROVIDERS: dict[str, callable] = {
    "icanhazdadjoke": fetch_from_icanhazdadjoke,
    "jokeapi": fetch_from_jokeapi,
    "groandeck": fetch_from_groandeck,
    "syrsly": fetch_from_syrsly,
    "api_ninjas": fetch_from_api_ninjas,
    "jokebot_jokebook": fetch_from_jokebot_jokebook,
}
