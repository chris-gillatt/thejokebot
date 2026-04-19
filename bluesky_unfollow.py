### File: bluesky_unfollow.py
import os
import time
from colorama import Fore, Style
from bluesky_follower_utils import fetch_paginated_data
from bluesky_common import login_client, get_runtime_controls

def unfollow_users():
    # List of usernames to ignore (configurable via BLUESKY_UNFOLLOW_IGNORE env var)
    default_ignorable = ["theonion"]
    env_ignorable = os.getenv("BLUESKY_UNFOLLOW_IGNORE", "")
    ignorable_usernames = default_ignorable + [u.strip() for u in env_ignorable.split(",") if u.strip()]
    ignorable_usernames = list(set(ignorable_usernames))  # Deduplicate
    client = None
    username = None
    controls = get_runtime_controls()
    dry_run = controls["dry_run"]
    action_delay_seconds = controls["action_delay_seconds"]

    if dry_run:
        print(f"{Fore.YELLOW}Dry-run mode enabled. Unfollow actions will not be executed.{Style.RESET_ALL}")
    if action_delay_seconds > 0:
        print(
            f"{Fore.YELLOW}Action delay enabled: {action_delay_seconds:.2f}s between actions.{Style.RESET_ALL}"
        )

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
        # Extract following DIDs and URIs
        following_map = {follow.did: follow.viewer.following for follow in following}

        # Map usernames to DIDs for ignorable accounts
        ignorable_dids = set()
        for ignorable_username in ignorable_usernames:
            try:
                profile = client.get_profile(ignorable_username)
                did = getattr(profile, "did", None)
                if not did and isinstance(profile, dict):
                    did = profile.get("did")

                if did:
                    ignorable_dids.add(did)
                    print(f"{Fore.GREEN}Resolved username {ignorable_username} to DID {did}{Style.RESET_ALL}")
                else:
                    print(f"{Fore.RED}No DID found for username {ignorable_username}, skipping ignore rule.{Style.RESET_ALL}")
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
                if dry_run:
                    print(f"{Fore.YELLOW}[DRY-RUN] Would unfollow {did}{Style.RESET_ALL}")
                else:
                    client.unfollow(uri)
                    print(f"{Fore.GREEN}Unfollowed {did}{Style.RESET_ALL}")

                if action_delay_seconds > 0 and i < len(to_unfollow):
                    time.sleep(action_delay_seconds)
            else:
                print(f"{Fore.RED}No URI found for {did}, skipping...{Style.RESET_ALL}")

        print(f"{Fore.GREEN}Unfollow actions completed! 🎉{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}An unexpected error occurred: {e}{Style.RESET_ALL}")

if __name__ == "__main__":
    unfollow_users()
