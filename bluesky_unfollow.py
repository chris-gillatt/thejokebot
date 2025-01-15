### File: bluesky_unfollow.py
from atproto import Client
import os
from colorama import Fore, Style
from bluesky_follower_utils import fetch_paginated_data

def unfollow_users():
    username = "thejokebot.bsky.social"
    password = os.getenv('BLUESKY_PASSWORD')

    # List of usernames to ignore
    ignorable_usernames = ["theonion"]

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
        # Extract following DIDs and URIs
        following_map = {follow.did: follow.viewer.following for follow in following}

        # Map usernames to DIDs for ignorable accounts
        ignorable_dids = set()
        for ignorable_username in ignorable_usernames:
            try:
                profile = client.get_profile(ignorable_username)
                ignorable_dids.add(profile['did'])
                print(f"{Fore.GREEN}Resolved username {ignorable_username} to DID {profile['did']}{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}Failed to resolve username {ignorable_username}: {e}{Style.RESET_ALL}")

        # Unfollow users who no longer follow us, excluding ignorable accounts
        to_unfollow = {
            did for did, uri in following_map.items()
            if did not in follower_dids and did not in ignorable_dids
        }
        print(f"{Fore.RED}Found {len(to_unfollow)} users to unfollow (excluding ignorable accounts).{Style.RESET_ALL}")

        for i, did in enumerate(to_unfollow, start=1):
            uri = following_map.get(did)
            if uri:
                print(f"{Fore.YELLOW}({i}/{len(to_unfollow)}) Unfollowing {did}...{Style.RESET_ALL}")
                client.delete_follow(uri)
                print(f"{Fore.GREEN}Unfollowed {did}{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}No URI found for {did}, skipping...{Style.RESET_ALL}")

        print(f"{Fore.GREEN}Unfollow actions completed! 🎉{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}An unexpected error occurred: {e}{Style.RESET_ALL}")

if __name__ == "__main__":
    unfollow_users()
