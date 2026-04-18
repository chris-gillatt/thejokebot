### File: bluesky_follow_back.py
from colorama import Fore, Style
from bluesky_follower_utils import fetch_paginated_data
from bluesky_common import login_client

def follow_back():
    client = None
    username = None

    try:
        print(f"{Fore.YELLOW}Logging in to BlueSky...{Style.RESET_ALL}")
        client, username = login_client()
        print(f"{Fore.GREEN}Successfully logged in to BlueSky.{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}Login failed: {e}{Style.RESET_ALL}")
        return

    try:
        user_did = client.me.did
        print(f"{Fore.YELLOW}Fetching followers and following for user: {username}{Style.RESET_ALL}")

        # Fetch followers and following
        followers = fetch_paginated_data(client.get_followers, user_did)
        following = fetch_paginated_data(client.get_follows, user_did)

        # Extract follower DIDs
        follower_dids = {follower.did for follower in followers}
        # Extract following DIDs
        following_dids = {follow.did for follow in following}

        # Follow back new followers
        to_follow_back = follower_dids - following_dids
        print(f"{Fore.GREEN}Found {len(to_follow_back)} followers to follow back.{Style.RESET_ALL}")

        for i, did in enumerate(to_follow_back, start=1):
            print(f"{Fore.YELLOW}({i}/{len(to_follow_back)}) Following {did}...{Style.RESET_ALL}")
            client.follow(did)
            print(f"{Fore.GREEN}Followed {did}{Style.RESET_ALL}")

        print(f"{Fore.GREEN}Follow-back actions completed! 🎉{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}An unexpected error occurred: {e}{Style.RESET_ALL}")

if __name__ == "__main__":
    follow_back()