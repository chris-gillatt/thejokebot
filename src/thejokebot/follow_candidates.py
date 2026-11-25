"""Verify follow candidates in the authenticated Bluesky view."""

from colorama import Fore, Style

from thejokebot.runtime import get_nested_value, retry_network_call

_PROFILE_BATCH_SIZE = 25


def eligible_follow_candidate_dids(client, dids: set[str]) -> set[str]:
    """Check candidate relationships and moderation in the authenticated view."""
    available: set[str] = set()
    ordered = sorted(dids)
    for offset in range(0, len(ordered), _PROFILE_BATCH_SIZE):
        actors = ordered[offset : offset + _PROFILE_BATCH_SIZE]
        response = retry_network_call(
            lambda current=actors: client.get_profiles(current),
            description="checking follow candidate profiles",
        )
        profiles = get_nested_value(response, "profiles")
        if not isinstance(profiles, list):
            raise ValueError("Unexpected follow candidate profile response")
        seen: set[str] = set()
        with_viewer = 0
        for profile in profiles:
            did = get_nested_value(profile, "did")
            if did not in actors or did in seen:
                raise ValueError("Follow candidate profile identity mismatch")
            seen.add(did)
            viewer = get_nested_value(profile, "viewer")
            if viewer is None:
                continue
            with_viewer += 1
            if not any(
                get_nested_value(viewer, field)
                for field in (
                    "blocking",
                    "blocking_by_list",
                    "blockingByList",
                    "blocked_by",
                    "blockedBy",
                    "muted",
                    "following",
                )
            ):
                available.add(did)
        if with_viewer < len(actors):
            print(
                f"{Fore.YELLOW}Skipped {len(actors) - with_viewer} unavailable "
                f"follow candidate profile(s).{Style.RESET_ALL}"
            )
    return available
