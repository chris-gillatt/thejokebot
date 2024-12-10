from atproto import Client
import os
from colorama import Fore, Style


def fetch_paginated_data(client_method, actor):
    """Fetch paginated data (followers or following)."""
    data = []
    cursor = None
    while True:
        response = client_method(actor=actor, cursor=cursor)
        if hasattr(response, 'followers'):
            data.extend(response.followers)  # For followers
        elif hasattr(response, 'follows'):
            data.extend(response.follows)  # For follows
        cursor = getattr(response, 'cursor', None)
        if not cursor:
            break
    return data


def main():
    username = "thejokebot.bsky.social"
    password = os.getenv('BLUESKY_PASSWORD')

    if not password:
        print(f"{Fore.RED}Error: Missing BLUESKY_PASSWORD in the environment.{Style.RESET_ALL}")
        return

    client = Client()

    try:
        print(f"{Fore.YELLOW}Logging in to BlueSky...{Style.RESET_ALL}")
        client.login(username, password)
        print(f"{Fore.GREEN}Successfully logged in to BlueSky.{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}Login failed: {e}{Style.RESET_ALL}")
        return

    try:
        user_did = client.me['did']
        print(f"{Fore.YELLOW}Fetching followers and following for user: {username}{Style.RESET_ALL}")

        # Fetch followers and following
        followers = fetch_paginated_data(client.get_followers, user_did)
        following = fetch_paginated_data(client.get_follows, user_did)

        # Extract follower DIDs
        follower_dids = {follower.did for follower in followers}

        # Extract following DIDs and URIs for all followed users
        following_map = {follow.did: follow.viewer.following for follow in following}
        following_dids = set(following_map.keys())

        # Follow back new followers
        to_follow_back = follower_dids - following_dids
        print(f"{Fore.GREEN}Found {len(to_follow_back)} followers to follow back.{Style.RESET_ALL}")

        for i, did in enumerate(to_follow_back, start=1):
            print(f"{Fore.YELLOW}({i}/{len(to_follow_back)}) Following {did}...{Style.RESET_ALL}")
            client.follow(did)
            print(f"{Fore.GREEN}Followed {did}{Style.RESET_ALL}")

        # Unfollow users who no longer follow the bot
        to_unfollow = {
            did for did, uri in following_map.items() if did not in follower_dids
        }
        print(f"{Fore.RED}Found {len(to_unfollow)} users to unfollow.{Style.RESET_ALL}")

        for i, did in enumerate(to_unfollow, start=1):
            uri = following_map.get(did)
            if uri:
                print(f"{Fore.YELLOW}({i}/{len(to_unfollow)}) Unfollowing {did}...{Style.RESET_ALL}")
                client.delete_follow(uri)
                print(f"{Fore.GREEN}Unfollowed {did}{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}No URI found for {did}, skipping...{Style.RESET_ALL}")

        print(f"{Fore.GREEN}Follow-back and unfollow actions completed! 🎉{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}An unexpected error occurred: {e}{Style.RESET_ALL}")


if __name__ == "__main__":
    main()
