import os
import time
from pathlib import Path

import atproto_client.exceptions
from atproto import Client
from dotenv import load_dotenv

DEFAULT_BLUESKY_USERNAME = "thejokebot.bsky.social"
DEFAULT_LOGIN_RETRY_ATTEMPTS = 3
DEFAULT_LOGIN_RETRY_DELAY_SECONDS = 2.0


def _load_local_env_file():
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)


_load_local_env_file()


def get_bluesky_credentials():
    username = os.getenv("BLUESKY_USERNAME", DEFAULT_BLUESKY_USERNAME).strip()
    password = os.getenv("BLUESKY_PASSWORD")

    if not password:
        raise ValueError(
            "BLUESKY_PASSWORD environment variable is not set. "
            "Please configure it in GitHub Actions secrets or local .env."
        )

    return username, password


def login_client():
    username, password = get_bluesky_credentials()
    raw_attempts = os.getenv("BLUESKY_LOGIN_RETRY_ATTEMPTS", str(DEFAULT_LOGIN_RETRY_ATTEMPTS))
    try:
        max_attempts = int(raw_attempts.strip())
    except ValueError:
        max_attempts = DEFAULT_LOGIN_RETRY_ATTEMPTS
    max_attempts = max(1, max_attempts)
    retry_delay_seconds = get_float_env(
        "BLUESKY_LOGIN_RETRY_DELAY_SECONDS",
        default=DEFAULT_LOGIN_RETRY_DELAY_SECONDS,
        minimum=0.0,
    )

    client = Client()
    for attempt in range(1, max_attempts + 1):
        try:
            client.login(username, password)
            return client, username
        except atproto_client.exceptions.NetworkError as exc:
            if attempt >= max_attempts:
                raise
            print(
                f"Warning: transient Bluesky login failure ({attempt}/{max_attempts}): {exc}. "
                f"Retrying in {retry_delay_seconds:.1f}s."
            )
            if retry_delay_seconds:
                time.sleep(retry_delay_seconds)


def get_bool_env(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default

    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def get_float_env(name, default=0.0, minimum=0.0):
    raw = os.getenv(name)
    if raw is None:
        return default

    try:
        value = float(raw.strip())
    except ValueError:
        return default

    if value < minimum:
        return minimum
    return value


def get_runtime_controls():
    return {
        "dry_run": get_bool_env("BLUESKY_DRY_RUN", default=False),
        "action_delay_seconds": get_float_env(
            "BLUESKY_ACTION_DELAY_SECONDS", default=0.0, minimum=0.0
        ),
    }
