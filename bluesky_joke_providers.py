### File: bluesky_joke_providers.py
"""
Joke provider functions for the joke bot.

Each provider is a callable with signature () -> str that returns a single
joke string (plain text, may contain newlines for two-part jokes) or raises
an exception if the joke cannot be fetched.

PROVIDERS maps provider name -> fetch function. Add new providers here and
they will be picked up by the rotation in bluesky_state.py automatically
(you must also add the name to PROVIDER_ROTATION_ORDER in bluesky_state.py).
"""
import requests

JOKE_TIMEOUT_SECONDS = 15

_USER_AGENT = "thejokebot (https://github.com/chris-gillatt/thejokebot)"
_ICANHAZDADJOKE_URL = "https://icanhazdadjoke.com"

# Safe categories only — Dark is excluded intentionally.
# safe-mode is embedded in the URL as a value-less parameter because requests
# drops params with None values and encodes empty strings as key=.
_JOKEAPI_URL = (
    "https://v2.jokeapi.dev/joke/Misc,Programming,Pun,Spooky,Christmas?safe-mode"
)
_JOKEAPI_BLACKLIST = "nsfw,explicit,racist,sexist"


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


# Registry — keys must match the names in bluesky_state.PROVIDER_ROTATION_ORDER.
PROVIDERS: dict[str, callable] = {
    "icanhazdadjoke": fetch_from_icanhazdadjoke,
    "jokeapi": fetch_from_jokeapi,
}
