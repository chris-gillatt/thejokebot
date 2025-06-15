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

def search_hashtag_posts(hashtag):
    try:
        print(f"Searching posts with hashtag #{hashtag}...")
        query = f"#{hashtag}"
        params = models.AppBskyFeedSearchPosts.Params(q=query, limit=max_results_per_tag)
        result = client.app.bsky.feed.search_posts(params)
        posts = result.posts or []
        dids = list({post.author.did for post in posts if post.author and post.author.did})
        print(f"Found {len(dids)} users for #{hashtag}")
        return dids
    except Exception as e:
        print(f"Exception during search for #{hashtag}: {e}")
        return []

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

    all_dids = set()
    for tag in hashtags:
        dids = search_hashtag_posts(tag)
        all_dids.update(dids)

    following_dids = get_following_dids()
    new_dids = [did for did in all_dids if did not in following_dids]

    print(f"Total users to follow: {len(new_dids)}")
    follow_users(new_dids)
    print("Follower generation script completed.")

if __name__ == "__main__":
    main()