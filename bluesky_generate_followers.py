import time
import random
import logging
import os
import requests
from datetime import datetime, timezone, timedelta
from atproto import Client

# Configurations
TAGS = ["#followback", "#dadjoke", "#jokes", "#funny"]
TARGET_FOLLOW_COUNT = 60
TAG_ALLOCATION = TARGET_FOLLOW_COUNT // len(TAGS)
TIME_LIMIT = datetime.now(timezone.utc) - timedelta(days=5)

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load credentials from environment
BLUESKY_USERNAME = os.getenv("BLUESKY_USERNAME", "thejokebot.bsky.social")
BLUESKY_PASSWORD = os.getenv("BLUESKY_PASSWORD")

if not BLUESKY_USERNAME or not BLUESKY_PASSWORD:
    raise ValueError("Bluesky credentials not found. Set BLUESKY_USERNAME and BLUESKY_PASSWORD as environment variables.")

# Initialise and login
client = Client()
client.login(BLUESKY_USERNAME, BLUESKY_PASSWORD)
my_did = client.me.did

# Public search API
PUBLIC_SEARCH_URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"

def get_following_list():
    """Retrieve a list of DIDs that the bot is already following."""
    following = set()
    cursor = None

    try:
        while True:
            result = client.app.bsky.graph.get_follows({
                "actor": my_did,
                "cursor": cursor
            })

            if hasattr(result, "follows"):
                following.update([f.did for f in result.follows])

            if not hasattr(result, "cursor") or not result.cursor:
                break

            cursor = result.cursor
            time.sleep(1)  # Rate limit padding

    except Exception as e:
        logging.error(f"Error fetching following list: {e}")

    return list(following)

def search_users_by_tag(tag, since_time):
    """Use the public API to find DIDs of users who recently used the tag."""
    users = set()
    since_iso = since_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        params = {
            "q": tag.lstrip("#"),
            "since": since_iso,
            "limit": 100
        }
        response = requests.get(PUBLIC_SEARCH_URL, params=params)
        response.raise_for_status()
        posts = response.json().get("posts", [])

        for post in posts:
            users.add(post["author"]["did"])

    except Exception as e:
        logging.error(f"Error searching posts for tag '{tag}': {e}")

    return list(users)

def follow_user(target_did):
    """Send a follow record manually using create_record()."""
    try:
        record = {
            "$type": "app.bsky.graph.follow",
            "subject": target_did,
            "createdAt": datetime.now(timezone.utc).isoformat()
        }

        response = client.com.atproto.repo.create_record({
            "repo": my_did,
            "collection": "app.bsky.graph.follow",
            "record": record
        })

        uri = response.uri
        logging.info(f"Followed {target_did} → {uri}")
        time.sleep(random.uniform(1.2, 2.5))

    except Exception as e:
        logging.error(f"Error following user {target_did}: {e}")
        if "429" in str(e):
            logging.warning("Rate limit hit — sleeping for 5 minutes")
            time.sleep(300)

def get_new_users_by_tag(tag, needed_count, following_list):
    found = search_users_by_tag(tag, since=TIME_LIMIT)
    return [u for u in found if u not in following_list][:needed_count]

def main():
    logging.info("Starting follower generation script...")
    following = get_following_list()
    new_follows = []
    tag_counts = {}
    remaining = TARGET_FOLLOW_COUNT

    for tag in TAGS:
        if remaining <= 0:
            break

        users = get_new_users_by_tag(tag, min(TAG_ALLOCATION, remaining), following)
        tag_counts[tag] = len(users)
        new_follows.extend(users)
        remaining -= len(users)

    logging.info(f"User count per tag: {tag_counts}")
    if remaining > 0:
        logging.warning(f"Not enough users found. Remaining slots: {remaining}")
    logging.info(f"Total users to follow: {len(new_follows)}")

    for user in new_follows:
        follow_user(user)

    logging.info("Follower generation script completed.")

if __name__ == "__main__":
    main()