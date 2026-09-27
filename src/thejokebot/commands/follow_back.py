"""Follow back followers who are not yet followed by the bot."""

from __future__ import annotations

import time

import atproto_client.exceptions
import requests
from colorama import Fore, Style

from thejokebot import state as bot_state
from thejokebot.followers import fetch_paginated_data
from thejokebot.runtime import mask_sensitive, retry_network_call

PAGE_LIMIT = 100
MAX_PAGES = 1000
MAX_RUNTIME_SECONDS = 180
MAX_RECONCILIATION_PASSES = 3
SETTLE_SECONDS = 5


def _follow_candidates(
    client,
    state,
    candidates,
    dry_run,
    action_delay_seconds,
    attempted_dids,
    summary,
):
    for index, did in enumerate(candidates, start=1):
        attempted_dids.add(did)
        masked_did = mask_sensitive(did)
        print(
            f"{Fore.YELLOW}({index}/{len(candidates)}) Following "
            f"{masked_did}...{Style.RESET_ALL}"
        )
        if dry_run:
            print(f"{Fore.YELLOW}[DRY-RUN] Would follow {masked_did}{Style.RESET_ALL}")
            summary["follow_back_added"] += 1
        else:
            try:
                retry_network_call(
                    lambda current_did=did: client.follow(current_did),
                    description=f"following back {masked_did}",
                )
                print(f"{Fore.GREEN}Followed {masked_did}{Style.RESET_ALL}")
                if state is not None:
                    bot_state.record_acquisition(state, did, "followback")
                summary["follow_back_added"] += 1
            except (
                requests.RequestException,
                TimeoutError,
                atproto_client.exceptions.NetworkError,
            ) as exc:
                print(
                    f"{Fore.RED}Failed to follow {masked_did}: {exc}{Style.RESET_ALL}"
                )
                summary["failed"] += 1

        if action_delay_seconds > 0 and index < len(candidates):
            time.sleep(action_delay_seconds)


def follow_back(
    client,
    dry_run: bool,
    action_delay_seconds: float,
    summary: dict | None = None,
    state: dict | None = None,
) -> None:
    """Follow every current follower that the bot is not yet following."""
    if summary is None:
        summary = {}
    user_did = client.me.did
    print(
        f"{Fore.YELLOW}Fetching followers and following for account.{Style.RESET_ALL}"
    )

    attempted_dids: set[str] = set()
    observed_candidate_dids: set[str] = set()
    cohorts_reconciled = False
    summary["follow_back_candidates"] = 0
    summary["follow_back_added"] = 0
    summary["failed"] = 0

    for pass_number in range(1, MAX_RECONCILIATION_PASSES + 2):
        followers = fetch_paginated_data(
            client.get_followers,
            actor=user_did,
            limit=PAGE_LIMIT,
            max_pages=MAX_PAGES,
            max_runtime_seconds=MAX_RUNTIME_SECONDS,
            require_complete=True,
        )
        following = fetch_paginated_data(
            client.get_follows,
            actor=user_did,
            limit=PAGE_LIMIT,
            max_pages=MAX_PAGES,
            max_runtime_seconds=MAX_RUNTIME_SECONDS,
            require_complete=True,
        )
        follower_dids = {follower.did for follower in followers}
        following_dids = {followed.did for followed in following}
        if state is not None and not dry_run and not cohorts_reconciled:
            bot_state.reconcile_acquisition_cohorts(state, follower_dids)
            cohorts_reconciled = True
        remaining_dids = follower_dids - following_dids
        observed_candidate_dids |= remaining_dids
        summary["follow_back_candidates"] = len(observed_candidate_dids)

        if not remaining_dids:
            print(
                f"{Fore.GREEN}Verified that all actionable followers are "
                f"followed back.{Style.RESET_ALL}"
            )
            print(f"{Fore.GREEN}Follow-back completed.{Style.RESET_ALL}")
            return

        if pass_number > MAX_RECONCILIATION_PASSES:
            summary["failed"] += len(remaining_dids)
            raise RuntimeError(
                "Follow-back did not converge after "
                f"{MAX_RECONCILIATION_PASSES} reconciliation passes; "
                f"{len(remaining_dids)} actionable follower(s) remain."
            )

        candidates = sorted(remaining_dids - attempted_dids)
        print(
            f"{Fore.GREEN}Follow-back pass {pass_number}: found "
            f"{len(remaining_dids)} actionable follower(s), "
            f"{len(candidates)} not yet attempted.{Style.RESET_ALL}"
        )
        _follow_candidates(
            client,
            state,
            candidates,
            dry_run,
            action_delay_seconds,
            attempted_dids,
            summary,
        )

        if dry_run:
            print(f"{Fore.GREEN}Follow-back dry run completed.{Style.RESET_ALL}")
            return

        time.sleep(SETTLE_SECONDS)
