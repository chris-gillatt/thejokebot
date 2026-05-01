import time

import requests

import atproto_client.exceptions
import bluesky_state
from bluesky_common import (
    get_runtime_controls,
    login_client,
    mask_sensitive,
    retry_network_call,
)
from bluesky_follower_utils import fetch_paginated_data

# Limits
soft_tag_limit = 15
global_follow_limit = 60
hashtags = ["followback", "dadjoke", "jokes", "funny"]


def fetch_users_for_tag(client, tag: str):
    print(f"Searching posts with hashtag #{tag}...")
    try:
        resp = retry_network_call(
            lambda: client.app.bsky.feed.search_posts(
                {"q": f"#{tag}", "tag": [tag], "limit": 100, "sort": "latest"}
            ),
            description=f"searching posts for #{tag}",
        )
        users = [post.author.did for post in resp.posts]
        print(f"Found {len(users)} users for #{tag}")
        return users
    except (
        requests.RequestException,
        TimeoutError,
        atproto_client.exceptions.NetworkError,
    ) as e:
        print(f"Exception during search for #{tag}: {e}")
        return []


def get_following(client):
    try:
        following = fetch_paginated_data(client.get_follows, client.me.did)
        return {follow.did for follow in following}
    except (
        requests.RequestException,
        TimeoutError,
        atproto_client.exceptions.NetworkError,
    ) as e:
        print(f"Could not fetch following list, proceeding without deduplication: {e}")
        return set()


def follow(client, did: str):
    masked_did = mask_sensitive(did)
    try:
        retry_network_call(
            lambda: client.follow(did),
            description=f"following {masked_did}",
        )
    except (
        requests.RequestException,
        TimeoutError,
        atproto_client.exceptions.NetworkError,
    ) as e:
        print(f"Unexpected error trying to follow {masked_did}: {e}")


def select_users(tag_users, tag_order, per_tag_limit, overall_limit):
    selected_users = []
    seen = set()

    for tag in tag_order:
        count = 0
        for user in tag_users[tag]:
            if user not in seen:
                seen.add(user)
                selected_users.append((tag, user))
                count += 1
                if count >= per_tag_limit:
                    break

    if len(selected_users) < overall_limit:
        additional_needed = overall_limit - len(selected_users)
        overflow = []
        for tag in tag_order:
            for user in tag_users[tag]:
                if user not in seen:
                    seen.add(user)
                    overflow.append((tag, user))
        selected_users += overflow[:additional_needed]

    return selected_users[:overall_limit]


def main():
    print("Starting fellow-follow discovery script...")
    client, username = login_client()
    print("Authenticated successfully.")
    controls = get_runtime_controls()
    dry_run = controls["dry_run"]
    action_delay_seconds = controls["action_delay_seconds"]

    if dry_run:
        print("Dry-run mode enabled. Follow actions will not be executed.")
    if action_delay_seconds > 0:
        print(f"Action delay enabled: {action_delay_seconds:.2f}s between actions.")

    already_following = get_following(client)
    state = bluesky_state.load_state()
    unfollowed_dids = bluesky_state.get_unfollowed_dids(state)
    if unfollowed_dids:
        print(
            f"{len(unfollowed_dids)} DID(s) in unfollow history — excluded from candidates."
        )

    tag_users = {}
    for tag in hashtags:
        users = fetch_users_for_tag(client, tag)
        eligible_users = [
            u for u in users if u not in already_following and u not in unfollowed_dids
        ]
        tag_users[tag] = eligible_users

    print("\nEligible users before redistribution:")
    for tag, users in tag_users.items():
        print(f"  #{tag}: {len(users)} users")

    selected_users = select_users(
        tag_users,
        hashtags,
        per_tag_limit=soft_tag_limit,
        overall_limit=global_follow_limit,
    )

    print("\nFinal tag breakdown:")
    tag_counts = {tag: 0 for tag in hashtags}
    for tag, _ in selected_users:
        tag_counts[tag] += 1
    for tag in hashtags:
        print(f"  #{tag}: {tag_counts[tag]} users")

    print(f"Total users to follow: {len(selected_users)}\n")

    for i, (tag, did) in enumerate(selected_users, start=1):
        masked_did = mask_sensitive(did)
        if dry_run:
            print(f"[DRY-RUN] Would follow {masked_did} (#{tag})")
        else:
            follow(client, did)

        if action_delay_seconds > 0 and i < len(selected_users):
            time.sleep(action_delay_seconds)

    print("\nFollowed users by tag:")
    for tag in hashtags:
        count = tag_counts[tag]
        if count == 0:
            print(f"  #{tag}: 0 users")
        else:
            print(f"  #{tag}: {count} users")

    print("\nFollow fellows script completed.")


if __name__ == "__main__":
    main()
