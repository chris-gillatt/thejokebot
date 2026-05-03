import os
import time
import json
import pathlib
import requests
import atproto_client.exceptions
from colorama import Fore, Style
from bluesky_follower_utils import (
    extract_list_member_did,
    fetch_list_member_dids,
    fetch_paginated_data,
)
from bluesky_common import (
    login_client,
    get_runtime_controls,
    retry_network_call,
    get_int_env,
    get_float_env,
    mask_sensitive,
)
import bluesky_state as _state


DEFAULT_UNFOLLOW_MAX_ACTIONS = 200
DEFAULT_UNFOLLOW_BATCH_SIZE = 50
DEFAULT_UNFOLLOW_BATCH_PAUSE_SECONDS = 60.0
_STARTER_PACK_CONFIG_PATH = (
    pathlib.Path(__file__).parent / "resources" / "jokebot_starter_pack.json"
)


def get_unfollow_controls():
    """Read unfollow safety controls from environment variables."""
    return {
        "max_actions": get_int_env(
            "BLUESKY_UNFOLLOW_MAX_ACTIONS",
            default=DEFAULT_UNFOLLOW_MAX_ACTIONS,
            minimum=0,
        ),
        "batch_size": get_int_env(
            "BLUESKY_UNFOLLOW_BATCH_SIZE",
            default=DEFAULT_UNFOLLOW_BATCH_SIZE,
            minimum=1,
        ),
        "batch_pause_seconds": get_float_env(
            "BLUESKY_UNFOLLOW_BATCH_PAUSE_SECONDS",
            default=DEFAULT_UNFOLLOW_BATCH_PAUSE_SECONDS,
            minimum=0.0,
        ),
    }


def select_unfollow_candidates(
    following_map, follower_dids, ignorable_dids, max_actions
):
    """Return deterministic DID candidates to unfollow with an optional safety cap."""
    candidates = sorted(
        did
        for did in following_map
        if did not in follower_dids and did not in ignorable_dids
    )
    if max_actions > 0:
        return candidates[:max_actions]
    return candidates


def _is_rate_limited_error(exc):
    text = str(exc).lower()
    return (
        "429" in text
        or "too many requests" in text
        or "rate limit" in text
        or "throttle" in text
    )


def _extract_list_member_did(item):
    return extract_list_member_did(item)


def _load_source_list_uri(config_path=_STARTER_PACK_CONFIG_PATH):
    if not config_path.exists():
        return ""

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""

    if not isinstance(payload, dict):
        return ""

    starter_pack = payload.get("starter_pack")
    if not isinstance(starter_pack, dict):
        return ""

    if not starter_pack.get("enabled"):
        return ""

    uri = str(starter_pack.get("source_list_uri") or "").strip()
    return uri if uri.startswith("at://") else ""


def _fetch_list_member_dids(client, list_uri):
    return fetch_list_member_dids(
        client,
        list_uri,
        description="fetching protected starter-pack list members",
    )


def unfollow_users():
    # List of usernames to ignore (configurable via BLUESKY_UNFOLLOW_IGNORE env var)
    default_ignorable = ["theonion.bsky.social"]
    env_ignorable = os.getenv("BLUESKY_UNFOLLOW_IGNORE", "")
    ignorable_usernames = default_ignorable + [
        u.strip() for u in env_ignorable.split(",") if u.strip()
    ]
    ignorable_usernames = list(set(ignorable_usernames))  # Deduplicate
    client = None
    username = None
    controls = get_runtime_controls()
    dry_run = controls["dry_run"]
    action_delay_seconds = controls["action_delay_seconds"]
    unfollow_controls = get_unfollow_controls()
    max_actions = unfollow_controls["max_actions"]
    batch_size = unfollow_controls["batch_size"]
    batch_pause_seconds = unfollow_controls["batch_pause_seconds"]

    if dry_run:
        print(
            f"{Fore.YELLOW}Dry-run mode enabled. Unfollow actions will not be executed.{Style.RESET_ALL}"
        )
    if action_delay_seconds > 0:
        print(
            f"{Fore.YELLOW}Action delay enabled: {action_delay_seconds:.2f}s between actions.{Style.RESET_ALL}"
        )
    cap_text = "no cap" if max_actions == 0 else str(max_actions)
    print(
        f"{Fore.YELLOW}Unfollow safety controls: max_actions={cap_text}, "
        f"batch_size={batch_size}, batch_pause={batch_pause_seconds:.2f}s.{Style.RESET_ALL}"
    )

    try:
        print(f"{Fore.YELLOW}Logging in to BlueSky...{Style.RESET_ALL}")
        client, username = login_client()
        print(f"{Fore.GREEN}Successfully logged in to BlueSky.{Style.RESET_ALL}")
    except (
        ValueError,
        requests.RequestException,
        TimeoutError,
        atproto_client.exceptions.NetworkError,
        atproto_client.exceptions.BadRequestError,
    ) as e:
        print(f"{Fore.RED}Login failed: {e}{Style.RESET_ALL}")
        return

    try:
        user_did = client.me.did
        print(
            f"{Fore.YELLOW}Fetching followers and following for account.{Style.RESET_ALL}"
        )

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
            masked_handle = mask_sensitive(ignorable_username)
            try:
                profile = retry_network_call(
                    lambda: client.get_profile(ignorable_username),
                    description=f"resolving profile {masked_handle}",
                )
                did = getattr(profile, "did", None)
                if not did and isinstance(profile, dict):
                    did = profile.get("did")

                if did:
                    ignorable_dids.add(did)
                    print(
                        f"{Fore.GREEN}Resolved username {masked_handle} to DID {mask_sensitive(did)}{Style.RESET_ALL}"
                    )
                else:
                    print(
                        f"{Fore.RED}No DID found for username {masked_handle}, skipping ignore rule.{Style.RESET_ALL}"
                    )
            except (
                ValueError,
                requests.RequestException,
                TimeoutError,
                atproto_client.exceptions.NetworkError,
                atproto_client.exceptions.BadRequestError,
            ) as e:
                print(
                    f"{Fore.RED}Failed to resolve username {masked_handle}: {e}{Style.RESET_ALL}"
                )

        source_list_uri = _load_source_list_uri()
        if source_list_uri:
            try:
                protected_list_dids = _fetch_list_member_dids(client, source_list_uri)
                ignorable_dids |= protected_list_dids
                print(
                    f"{Fore.GREEN}Loaded {len(protected_list_dids)} protected DID(s) "
                    f"from source list {source_list_uri}.{Style.RESET_ALL}"
                )
            except (
                ValueError,
                requests.RequestException,
                TimeoutError,
                atproto_client.exceptions.NetworkError,
                atproto_client.exceptions.BadRequestError,
            ) as e:
                print(
                    f"{Fore.RED}Failed to load protected list members from starter-pack config: {e}. "
                    f"Continuing with env-based ignores only.{Style.RESET_ALL}"
                )

        to_unfollow_all = select_unfollow_candidates(
            following_map,
            follower_dids,
            ignorable_dids,
            max_actions=0,
        )
        to_unfollow = select_unfollow_candidates(
            following_map,
            follower_dids,
            ignorable_dids,
            max_actions=max_actions,
        )

        print(
            f"{Fore.RED}Found {len(to_unfollow_all)} users to unfollow "
            f"(excluding ignorable accounts).{Style.RESET_ALL}"
        )
        if len(to_unfollow) < len(to_unfollow_all):
            print(
                f"{Fore.YELLOW}Safety cap active: processing first {len(to_unfollow)} this run. "
                f"Re-run workflow for next batch.{Style.RESET_ALL}"
            )

        unfollowed_count = 0
        failed_count = 0
        skipped_missing_uri = 0
        stop_early = False

        state = _state.load_state()
        _state.prune_follow_grace(state)
        follow_grace_dids = _state.get_follow_grace_dids(state)
        if follow_grace_dids:
            ignorable_dids |= follow_grace_dids
            print(
                f"{Fore.GREEN}Loaded {len(follow_grace_dids)} follow-grace DID(s) "
                f"within the {_state.FOLLOW_RESPONSE_GRACE_PERIOD_DAYS}-day response window.{Style.RESET_ALL}"
            )

        for i, did in enumerate(to_unfollow, start=1):
            masked_did = mask_sensitive(did)
            uri = following_map.get(did)
            if uri:
                print(
                    f"{Fore.YELLOW}({i}/{len(to_unfollow)}) Unfollowing {masked_did}...{Style.RESET_ALL}"
                )
                if dry_run:
                    print(
                        f"{Fore.YELLOW}[DRY-RUN] Would unfollow {masked_did}{Style.RESET_ALL}"
                    )
                    unfollowed_count += 1
                else:
                    try:
                        retry_network_call(
                            lambda u=uri: client.unfollow(u),
                            description=f"unfollowing {masked_did}",
                        )
                        print(f"{Fore.GREEN}Unfollowed {masked_did}{Style.RESET_ALL}")
                        unfollowed_count += 1
                        _state.record_unfollow(state, did)
                    except (
                        ValueError,
                        requests.RequestException,
                        TimeoutError,
                        atproto_client.exceptions.NetworkError,
                        atproto_client.exceptions.BadRequestError,
                    ) as e:
                        failed_count += 1
                        print(
                            f"{Fore.RED}Failed to unfollow {masked_did}: {e}{Style.RESET_ALL}"
                        )
                        if _is_rate_limited_error(e):
                            print(
                                f"{Fore.RED}Rate limit/throttle detected. "
                                f"Stopping early to avoid account risk.{Style.RESET_ALL}"
                            )
                            stop_early = True
                            break

                if action_delay_seconds > 0 and i < len(to_unfollow):
                    time.sleep(action_delay_seconds)

                if (
                    batch_size > 0
                    and batch_pause_seconds > 0
                    and i % batch_size == 0
                    and i < len(to_unfollow)
                ):
                    print(
                        f"{Fore.YELLOW}Batch boundary reached ({i}/{len(to_unfollow)}). "
                        f"Pausing for {batch_pause_seconds:.2f}s.{Style.RESET_ALL}"
                    )
                    time.sleep(batch_pause_seconds)
            else:
                print(
                    f"{Fore.RED}No URI found for {masked_did}, skipping...{Style.RESET_ALL}"
                )
                skipped_missing_uri += 1

        if stop_early:
            print(
                f"{Fore.YELLOW}Run stopped early after throttle detection. "
                f"Wait before running the next batch.{Style.RESET_ALL}"
            )

        print(
            f"{Fore.GREEN}Summary: processed={len(to_unfollow)}, "
            f"unfollowed={unfollowed_count}, failed={failed_count}, "
            f"missing_uri={skipped_missing_uri}.{Style.RESET_ALL}"
        )
        _state.prune_unfollow_history(state)
        _state.save_state(state)
        print(f"{Fore.GREEN}Unfollow actions completed! 🎉{Style.RESET_ALL}")
    except (
        ValueError,
        requests.RequestException,
        TimeoutError,
        atproto_client.exceptions.NetworkError,
        atproto_client.exceptions.BadRequestError,
    ) as e:
        print(f"{Fore.RED}An unexpected error occurred: {e}{Style.RESET_ALL}")


if __name__ == "__main__":
    unfollow_users()
