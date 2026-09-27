"""Follow back new followers and like reply/repost interactions."""

from __future__ import annotations

import requests
import atproto_client.exceptions
from colorama import Fore, Style

from thejokebot import blocks as blocks
from thejokebot import state as bot_state
from thejokebot.commands import follow_back as follow_back_processing
from thejokebot.commands import follow_interactors as follow_interactor_processing
from thejokebot.commands import interaction_likes
from thejokebot.commands import joke_requests
from thejokebot.commands import starter_pack_attribution
from thejokebot.runtime import (
    get_runtime_controls,
    login_client,
    retry_network_call,
)

# Transitional aliases keep the existing test seam stable while the social test
# suite is split by domain later in this phase.
_joke_request_candidate = joke_requests.request_candidate
_select_reply_joke = joke_requests.select_reply_joke
_JOKE_REQUEST_MAX_PAGES = joke_requests._MAX_PAGES
joke_denylist = joke_requests.joke_denylist
joke_posting = joke_requests.joke_posting

_FOLLOW_BACK_PAGE_LIMIT = follow_back_processing.PAGE_LIMIT
_FOLLOW_BACK_MAX_PAGES = follow_back_processing.MAX_PAGES
_FOLLOW_BACK_MAX_RUNTIME_SECONDS = follow_back_processing.MAX_RUNTIME_SECONDS
_SOCIAL_SUMMARY_FIELDS = (
    "follow_back_candidates",
    "follow_back_added",
    "protected",
    "interaction_candidates",
    "interaction_eligible",
    "interaction_added",
    "interactions_liked",
    "joke_replies",
    "starter_pack_follows",
    "starter_pack_scan_complete",
    "failed",
)


def _social_summary_line(summary: dict, dry_run: bool) -> str:
    counts = ", ".join(
        f"{field}={int(summary.get(field) or 0)}" for field in _SOCIAL_SUMMARY_FIELDS
    )
    return f"Social summary: {counts}, dry_run={'true' if dry_run else 'false'}."


def reply_to_joke_requests(client, username, state, dry_run, summary=None):
    """Delegate joke requests to their domain module."""
    joke_requests.retry_network_call = retry_network_call
    joke_requests.select_reply_joke = _select_reply_joke
    joke_requests._MAX_PAGES = _JOKE_REQUEST_MAX_PAGES
    return joke_requests.reply_to_joke_requests(
        client, username, state, dry_run, summary
    )


def follow_back(
    client,
    dry_run: bool,
    action_delay_seconds: float,
    summary: dict | None = None,
    state: dict | None = None,
) -> None:
    """Delegate follower reconciliation to its domain module."""
    return follow_back_processing.follow_back(
        client,
        dry_run,
        action_delay_seconds,
        summary,
        state,
    )


def follow_interactors(
    client,
    state: dict,
    dry_run: bool,
    action_delay_seconds: float,
    summary: dict | None = None,
) -> int:
    """Delegate interaction-follow processing to its domain module."""
    return follow_interactor_processing.follow_interactors(
        client, state, dry_run, action_delay_seconds, summary
    )


# ---------------------------------------------------------------------------
# Reply likes
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Starter-pack attribution
# ---------------------------------------------------------------------------


def track_starter_pack_follows(
    client, state: dict, dry_run: bool, summary: dict | None = None
) -> int:
    """Delegate starter-pack attribution to its domain module."""
    starter_pack_attribution.retry_network_call = retry_network_call
    return starter_pack_attribution.track_starter_pack_follows(
        client, state, dry_run, summary
    )


def like_replies(
    client,
    state: dict,
    dry_run: bool,
    action_delay_seconds: float,
    summary: dict | None = None,
) -> int:
    """Delegate interaction liking to its domain module."""
    interaction_likes.retry_network_call = retry_network_call
    return interaction_likes.like_replies(
        client, state, dry_run, action_delay_seconds, summary
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    controls = get_runtime_controls()
    dry_run = controls["dry_run"]
    action_delay_seconds = controls["action_delay_seconds"]

    if dry_run:
        print(
            f"{Fore.YELLOW}Dry-run mode enabled. Actions will not be executed.{Style.RESET_ALL}"
        )
    if action_delay_seconds > 0:
        print(
            f"{Fore.YELLOW}Action delay enabled: {action_delay_seconds:.2f}s between actions.{Style.RESET_ALL}"
        )

    try:
        print(f"{Fore.YELLOW}Logging in to Bluesky...{Style.RESET_ALL}")
        client, username = login_client()
        print(f"{Fore.GREEN}Successfully logged in.{Style.RESET_ALL}")
    except (
        ValueError,
        requests.RequestException,
        TimeoutError,
        atproto_client.exceptions.NetworkError,
    ) as exc:
        print(f"{Fore.RED}Login failed: {exc}{Style.RESET_ALL}")
        return

    reconciled_blocks = blocks.reconcile_configured_blocks(
        client,
        dry_run=dry_run,
        action_delay_seconds=action_delay_seconds,
    )
    if reconciled_blocks:
        action = "would require" if dry_run else "required"
        print(
            f"{Fore.GREEN}{reconciled_blocks} configured block"
            f"{'s' if reconciled_blocks != 1 else ''} {action} action.{Style.RESET_ALL}"
        )

    state = bot_state.load_state()
    social_summary = {
        "follow_back_candidates": 0,
        "follow_back_added": 0,
        "protected": 0,
        "interaction_candidates": 0,
        "interaction_eligible": 0,
        "interaction_added": 0,
        "interactions_liked": 0,
        "joke_replies": 0,
        "starter_pack_follows": 0,
        "starter_pack_scan_complete": 0,
        "failed": 0,
    }

    try:
        follow_back(
            client,
            dry_run,
            action_delay_seconds,
            social_summary,
            state,
        )
    except (
        ValueError,
        requests.RequestException,
        TimeoutError,
        atproto_client.exceptions.NetworkError,
    ) as exc:
        social_summary["failed"] += 1
        print(f"{Fore.RED}Follow-back failed: {exc}{Style.RESET_ALL}")

    try:
        followed = follow_interactors(
            client, state, dry_run, action_delay_seconds, social_summary
        )
        print(
            f"{Fore.GREEN}Followed {followed} new interactor"
            f"{'s' if followed != 1 else ''}.{Style.RESET_ALL}"
        )
    except (
        ValueError,
        requests.RequestException,
        TimeoutError,
        atproto_client.exceptions.NetworkError,
    ) as exc:
        social_summary["failed"] += 1
        print(f"{Fore.RED}Interaction-follow failed: {exc}{Style.RESET_ALL}")

    attributed_follows = track_starter_pack_follows(
        client, state, dry_run, social_summary
    )

    try:
        replied = reply_to_joke_requests(
            client, username, state, dry_run, social_summary
        )
        print(f"{Fore.GREEN}Replied to {replied} joke request(s).{Style.RESET_ALL}")
    except (
        ValueError,
        requests.RequestException,
        TimeoutError,
        atproto_client.exceptions.NetworkError,
    ) as exc:
        social_summary["failed"] += 1
        print(f"{Fore.RED}Joke-request replies failed: {exc}{Style.RESET_ALL}")
    print(
        f"{Fore.GREEN}Observed {attributed_follows} new starter-pack follow"
        f"{'s' if attributed_follows != 1 else ''}.{Style.RESET_ALL}"
    )

    try:
        liked = like_replies(
            client, state, dry_run, action_delay_seconds, social_summary
        )
        print(
            f"{Fore.GREEN}Liked {liked} new interaction"
            f"{'s' if liked != 1 else ''}.{Style.RESET_ALL}"
        )
    except (
        ValueError,
        requests.RequestException,
        TimeoutError,
        atproto_client.exceptions.NetworkError,
    ) as exc:
        social_summary["failed"] += 1
        print(f"{Fore.RED}Interaction liking failed: {exc}{Style.RESET_ALL}")

    print(_social_summary_line(social_summary, dry_run))
    bot_state.save_state(state, domains="social")
    if social_summary["failed"]:
        raise RuntimeError(
            f"Social run completed with {social_summary['failed']} failed action(s)."
        )
    print(f"{Fore.GREEN}Done.{Style.RESET_ALL}")


if __name__ == "__main__":
    main()
