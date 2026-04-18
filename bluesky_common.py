import os
from atproto import Client

DEFAULT_BLUESKY_USERNAME = "thejokebot.bsky.social"


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
    client = Client()
    client.login(username, password)
    return client, username
