import time
import random
import logging
import os
import requests
from datetime import datetime, timezone, timedelta
from atproto import Client, models

# Configurations
TAGS = ["#followback", "#dadjoke", "#jokes", "#funny"]
TARGET_FOLLOW_COUNT = 60
TAG_ALLOCATION = TARGET_FOLLOW_COUNT // len(TAGS)  # 15 per tag
TIME_LIMIT = datetime.now(timezone.utc) - timedelta(days=5)

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize and authenticate Bluesky API client
BLUESKY_USERNAME = "thejokebot.bsky.social"
BLUESKY_PASSWORD = os.getenv("BLUESKY_PASSWORD")

if not BLUESKY_USERNAME or not BLUESKY_PASSWORD:
    raise ValueError("Bluesky credentials not found. Please set BLUESKY_USERNAME and BLUESKY_PASSWORD as environment variables.")

client = Client()
client.login(BLUESKY_USERNAME, BLUESKY_PASSWORD)

PUBLIC_SEARCH_URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"

def get_following_list():
    """Retrieve a list of users the bot is already following."""
    try:
        following = set()
        cursor = None

        while True:
            params = {"actor": client.me.did, "cursor": cursor}
            response = client.app.bsky.graph.get_follows(params)

            if not response or not hasattr(response, 'follows'):
                break

            following.update([follow.did for follow in response.follows])
            cursor = response.cursor if hasattr(response, 'cursor') else None
            if not cursor:
                break

            time.sleep(1)  # Respect API rate limits

        return list(following)

    except Exception as e:
        logging.error(f"Error retrieving following list: {e}")
        return []

def search_users_by_tag(tag, since):
    """Search for users who have recently used a specific tag using the public API."""
    try:
        users = set()
        since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")  # ISO format
        params = {"q": tag.lstrip("#"), "since": since_iso}

        response = requests.get(PUBLIC_SEARCH_URL, params=params)
        response.raise_for_status()
        data = response.json()

        if "posts" not in data:
            return []

        for post in data["posts"]:
            users.add(post["author"]["did"])

        return list(users)

    except Exception as e:
        logging.error(f"Error searching users by tag {tag}: {e}")
        return []

def follow_user(user_did):
    """Follow a user on Bluesky with rate limit handling."""
    try:
        record = models.AppBskyGraphFollow.Main(
            created_at=datetime.now(timezone.utc).isoformat(),
            subject=user_did,
        )
        response = client.app.bsky.graph.follow.create(
            repo=client.me.did,
            data=record,
        )
        logging.info(f"Followed user: {user_did} - URI: {response.uri}")
        time.sleep(random.uniform(1, 2))  # Rate limiting
    except Exception as e:
        logging.error(f"Error following user {user_did}: {e}")
        if "429" in str(e):
            logging.warning("Rate limit hit. Sleeping for 5 minutes.")
            time.sleep(300)

def get_new_users_by_tag(tag, needed_count, following_list):
    """Search for users by tag and return a list of users not already followed."""
    found_users = search_users_by_tag(tag, since=TIME_LIMIT)
    new_users = [user for user in found_users if user not in following_list]
    return new_users[:needed_count]  # Trim excess if necessary

def main():
    logging.info("Starting follower generation script...")
    following_list = get_following_list()  # Get list of current follows
    new_follows = []
    tag_user_counts = {}
    remaining_slots = TARGET_FOLLOW_COUNT

    for tag in TAGS:
        if remaining_slots <= 0:
            break

        users = get_new_users_by_tag(tag, min(TAG_ALLOCATION, remaining_slots), following_list)
        tag_user_counts[tag] = len(users)
        new_follows.extend(users)
        remaining_slots -= len(users)

    logging.info(f"User count per tag: {tag_user_counts}")
    if remaining_slots > 0:
        logging.warning(f"Not enough users found. Remaining slots: {remaining_slots}")

    logging.info(f"Total users to follow: {len(new_follows)}")

    for user in new_follows:
        follow_user(user)

    logging.info("Follower generation script completed.")

if __name__ == "__main__":
    main()