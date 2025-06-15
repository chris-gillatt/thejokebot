import asyncio
import os
import random
from atproto import Client, models
from atproto_client.models.app.bsky.feed.search_posts import Response as SearchResponse

# Load credentials from environment
username = os.getenv("BLUESKY_USERNAME")
password = os.getenv("BLUESKY_PASSWORD")

# Limits
soft_tag_limit = 15
global_follow_limit = 60
hashtags = ["followback", "dadjoke", "jokes", "funny"]

client = Client()

def login():
    client.login(username, password)
    print(f"Authenticated as {client.me.did}")

def fetch_users_for_tag(tag: str):
    print(f"Searching posts with hashtag #{tag}...")
    try:
        resp: SearchResponse = client.app.bsky.feed.search_posts({"q": f"#{tag}", "limit": 100})
        users = [post.author.did for post in resp.posts]
        print(f"Found {len(users)} users for #{tag}")
        return users
    except Exception as e:
        print(f"Exception during search for #{tag}: {e}")
        return []

def get_following():
    try:
        resp = client.app.bsky.graph.get_follows({"actor": client.me.did, "limit": 100})
        return {follow.did for follow in resp.follows}
    except Exception as e:
        print(f"Could not fetch following list, proceeding without deduplication: {e}")
        return set()

def follow(did: str):
    try:
        record = models.AppBskyGraphFollow.Record(
            subject=did,
            created_at=client.get_current_time_iso()
        )
        client.com.atproto.repo.create_record(
            models.ComAtprotoRepoCreateRecord.Data(
                repo=client.me.did,
                collection="app.bsky.graph.follow",
                record=record,
            )
        )
        print(f"Following DID: {did}")
    except Exception as e:
        print(f"Unexpected error trying to follow {did}: {e}")

def main():
    print("Starting follower generation script...")
    login()

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

    for _, did in selected_users:
        follow(did)

    print("Follower generation script completed.")

if __name__ == "__main__":
    main()