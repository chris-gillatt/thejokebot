# bluesky_autofollow.py

import os
import sys
from atproto import Client
from colorama import Fore, Style


def fetch_paginated_data(client_method, actor, key):
    """Fetch paginated data (followers or following)."""
    data = []
    cursor = None
    while True:
        response = client_method(actor=actor, cursor=cursor)
        data.extend(response.get(key, []))
        cursor = response.get('cursor')
        if not cursor:
            break
    return data


def main():
    username = "thejokebot.bsky.social"
    password = os.getenv('BLUESKY_PASSWORD')

    if not username or not password:
        print(f"{Fore.RED}Error: Missing BLUESKY_USERNAME or BLUESKY_PASSWORD in the environment.{Style.RESET_ALL}")
        sys.exit(1)

    client = Client()

    try:
        print(f"{Fore.YELLOW}Logging in to BlueSky...{Style.RESET_ALL}")
        client.login(username, password)
        print(f"{Fore.GREEN}Successfully logged in to BlueSky.{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}Login failed: {e}{Style.RESET_ALL}")
        sys.exit(1)

    try:
        user_did = client.me['did']
        print(f"{Fore.YELLOW}Fetching followers and following for user: {client.me['handle']}{Style.RESET_ALL}")

        # Fetch followers and following
        followers = fetch_paginated_data(client.get_followers, user_did, 'followers')
        following = fetch_paginated_data(client.get_follows, user_did, 'follows')

        follower_dids = {follower['did'] for follower in followers}
        following_map = {follow['did']: follow['uri'] for follow in following}

        following_dids = set(following_map.keys())

        # Follow back new followers
        to_follow_back = follower_dids - following_dids
        print(f"{Fore.GREEN}Found {len(to_follow_back)} followers to follow back.{Style.RESET_ALL}")

        for i, did in enumerate(to_follow_back, start=1):
            print(f"{Fore.YELLOW}({i}/{len(to_follow_back)}) Following {did}...{Style.RESET_ALL}")
            client.follow(did)
            print(f"{Fore.GREEN}Followed {did}{Style.RESET_ALL}")

        # Unfollow users who no longer follow you
        to_unfollow = following_dids - follower_dids
        print(f"{Fore.RED}Found {len(to_unfollow)} users to unfollow.{Style.RESET_ALL}")

        for i, did in enumerate(to_unfollow, start=1):
            uri = following_map[did]
            print(f"{Fore.YELLOW}({i}/{len(to_unfollow)}) Unfollowing {did} with URI {uri}...{Style.RESET_ALL}")
            client.delete_follow(uri)
            print(f"{Fore.GREEN}Unfollowed {did}{Style.RESET_ALL}")

        print(f"{Fore.GREEN}Follow-back and unfollow actions completed! 🎉{Style.RESET_ALL}")
    except KeyError as e:
        print(f"{Fore.RED}Error: Missing expected data in API response: {e}{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}An unexpected error occurred: {e}{Style.RESET_ALL}")
        sys.exit(1)


if __name__ == "__main__":
    main()
