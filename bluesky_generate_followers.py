import os
from atproto import Client, models
from atproto.exceptions import AtProtocolError
from datetime import datetime

# Config
username = os.getenv("BLUESKY_USERNAME")
password = os.getenv("BLUESKY_PASSWORD")
hashtags = ["followback", "dadjoke", "jokes", "funny"]
max_results_per_tag = 20

client = Client()

def login():
    print("Logging in...")
    client.login(username, password)
    print(f"Authenticated as {client.me.did}")

def get_following_dids():
    try:
        following = []
        cursor = None
        while True:
            params = models.AppBskyGraphGetFollows.Params(actor=client.me.did, limit=100, cursor=cursor)
            result = client.app.bsky.graph.get_follows(params)
            follows = result.follows or []
            following.extend([user.did for user in follows])
            if not result.cursor:
                break
            cursor = result.cursor
        return set(following)
    except Exception as e:
        print(f"Could not fetch following list, proceeding without deduplication: {e}")
        return set()

def search_hashtag_posts(hashtag, already_following, already_seen):
    try:
        print(f"Searching posts with hashtag #{hashtag}...")
        query = f"#{hashtag}"
        params = models.AppBskyFeedSearchPosts.Params(q=query, limit=50)
        result = client.app.bsky.feed.search_posts(params)
        posts = result.posts or []

        new_dids = []
        for post in posts:
            did = post.author.did
            if did not in already_following and did not in already_seen:
                new_dids.append(did)
                already_seen.add(did)
            if len(new_dids) >= max_results_per_tag:
                break

        print(f"Found {len(new_dids)} new users for #{hashtag}")
        return new_dids
    except Exception as e:
        print(f"Exception during search for #{hashtag}: {e}")
        return []

def follow_users(user_dids):
    followed = 0
    for did in user_dids:
        try:
            print(f"Following DID: {did}")
            record = models.AppBskyGraphFollow.Record(
                subject=did,
                created_at=datetime.utcnow().isoformat() + 'Z'
            )
            client.app.bsky.graph.follow.create(
                repo=client.me.did,
                record=record
            )
            followed += 1
        except AtProtocolError as e:
            print(f"Failed to follow {did}: {e}")
        except Exception as e:
            print(f"Unexpected error trying to follow {did}: {e}")
    return followed

def main():
    print("Starting follower generation script...")
    login()

    already_following = get_following_dids()
    already_seen = set()
    new_follow_targets = []

    for tag in hashtags:
        tag_dids = search_hashtag_posts(tag, already_following, already_seen)
        new_follow_targets.extend(tag_dids)

    total_after_filter = len(new_follow_targets)
    print(f"\nSummary:")
    print(f"- Total unique new users to follow: {total_after_filter}")
    print(f"- Total already followed (skipped): {len(already_following & already_seen)}")
    print(f"- Total duplicates across hashtags (skipped): {len(already_seen) - total_after_filter}")

    follow_users(new_follow_targets)
    print("Follower generation script completed.")

if __name__ == "__main__":
    main()