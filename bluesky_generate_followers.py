import os
import time
from atproto import Client
from bluesky_common import login_client, get_runtime_controls
from bluesky_follower_utils import fetch_paginated_data

# Load credentials from environment
username = os.getenv("BLUESKY_USERNAME")

# Limits
soft_tag_limit = 15
global_follow_limit = 60
hashtags = ["followback", "dadjoke", "jokes", "funny"]

client = Client()

def login():
    global client, username
    client, username = login_client()
    print(f"Authenticated as {client.me.did} ({username})")

def fetch_users_for_tag(tag: str):
    print(f"Searching posts with hashtag #{tag}...")
    try:
        resp = client.app.bsky.feed.search_posts(
            {"q": f"#{tag}", "tag": [tag], "limit": 100, "sort": "latest"}
        )
        users = [post.author.did for post in resp.posts]
        print(f"Found {len(users)} users for #{tag}")
        return users
    except Exception as e:
        print(f"Exception during search for #{tag}: {e}")
        return []

def get_following():
    try:
        following = fetch_paginated_data(client.get_follows, client.me.did)
        return {follow.did for follow in following}
    except Exception as e:
        print(f"Could not fetch following list, proceeding without deduplication: {e}")
        return set()

def follow(did: str):
    try:
        client.follow(did)
        print(f"Following DID: {did}")
    except Exception as e:
        print(f"Unexpected error trying to follow {did}: {e}")

def main():
    print("Starting follower generation script...")
    login()
    controls = get_runtime_controls()
    dry_run = controls["dry_run"]
    action_delay_seconds = controls["action_delay_seconds"]

    if dry_run:
        print("Dry-run mode enabled. Follow actions will not be executed.")
    if action_delay_seconds > 0:
        print(f"Action delay enabled: {action_delay_seconds:.2f}s between actions.")

    already_following = get_following()

    tag_users = {}
    for tag in hashtags:
        users = fetch_users_for_tag(tag)
        eligible_users = [u for u in users if u not in already_following]
        tag_users[tag] = eligible_users

    print("\nEligible users before redistribution:")
    for tag, users in tag_users.items():
        print(f"  #{tag}: {len(users)} users")

    selected_users = []
    seen = set()

    for tag in hashtags:
        count = 0
        for user in tag_users[tag]:
            if user not in seen:
                seen.add(user)
                selected_users.append((tag, user))
                count += 1
                if count >= soft_tag_limit:
                    break

    if len(selected_users) < global_follow_limit:
        additional_needed = global_follow_limit - len(selected_users)
        overflow = []
        for tag in hashtags:
            for user in tag_users[tag]:
                if user not in seen:
                    seen.add(user)
                    overflow.append((tag, user))
        selected_users += overflow[:additional_needed]

    selected_users = selected_users[:global_follow_limit]

    print("\nFinal tag breakdown:")
    tag_counts = {tag: 0 for tag in hashtags}
    for tag, _ in selected_users:
        tag_counts[tag] += 1
    for tag in hashtags:
        print(f"  #{tag}: {tag_counts[tag]} users")

    print(f"Total users to follow: {len(selected_users)}\n")

    for i, (_, did) in enumerate(selected_users, start=1):
        if dry_run:
            print(f"[DRY-RUN] Would follow DID: {did}")
        else:
            follow(did)

        if action_delay_seconds > 0 and i < len(selected_users):
            time.sleep(action_delay_seconds)

    print("Follower generation script completed.")

if __name__ == "__main__":
    main()