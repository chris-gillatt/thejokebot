"""Create/synchronise The Joke Bot starter pack from a configured source list."""

import argparse
import datetime as dt
import json
import pathlib
import time

import atproto_client.exceptions
import requests

from bluesky_common import get_runtime_controls, login_client, retry_network_call
from bluesky_follower_utils import fetch_paginated_data

_CONFIG_PATH = pathlib.Path(__file__).parent / "resources" / "jokebot_starter_pack.json"


def load_starter_pack_config() -> dict:
    """Load starter-pack config from disk with safe defaults."""
    default = {
        "starter_pack": {
            "enabled": False,
            "name": "The Joke Bot Funnies",
            "description": "Starter pack built from The Joke Bot's Funnies list.",
            "source_list_uri": "",
            "record_key": "the-joke-bot-funnies",
            "sync": {
                "follow_list_members": True,
                "upsert_record": True,
            },
        }
    }

    if not _CONFIG_PATH.exists():
        return default

    try:
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Warning: failed to read starter-pack config: {exc}")
        return default

    if not isinstance(data, dict):
        return default

    starter = data.get("starter_pack")
    if not isinstance(starter, dict):
        return default

    sync = starter.get("sync") if isinstance(starter.get("sync"), dict) else {}

    default["starter_pack"].update(
        {
            "enabled": bool(starter.get("enabled", default["starter_pack"]["enabled"])),
            "name": str(starter.get("name", default["starter_pack"]["name"])).strip(),
            "description": str(
                starter.get("description", default["starter_pack"]["description"])
            ).strip(),
            "source_list_uri": str(
                starter.get("source_list_uri", default["starter_pack"]["source_list_uri"])
            ).strip(),
            "record_key": str(
                starter.get("record_key", default["starter_pack"]["record_key"])
            ).strip(),
        }
    )
    default["starter_pack"]["sync"].update(
        {
            "follow_list_members": bool(
                sync.get(
                    "follow_list_members",
                    default["starter_pack"]["sync"]["follow_list_members"],
                )
            ),
            "upsert_record": bool(
                sync.get("upsert_record", default["starter_pack"]["sync"]["upsert_record"])
            ),
        }
    )

    return default


def extract_list_member_did(item) -> str:
    """Extract a DID from a getList item payload."""
    subject = getattr(item, "subject", None)
    if subject is None and isinstance(item, dict):
        subject = item.get("subject")

    if isinstance(subject, str) and subject.startswith("did:"):
        return subject.strip()

    did = getattr(subject, "did", None)
    if did is None and isinstance(subject, dict):
        did = subject.get("did")

    return str(did or "").strip()


def fetch_list_member_dids(client, list_uri: str) -> set[str]:
    """Return all DIDs from a Bluesky list URI."""
    dids: set[str] = set()
    cursor = None

    while True:
        params = {"list": list_uri, "limit": 100}
        if cursor:
            params["cursor"] = cursor

        resp = retry_network_call(
            lambda: client.app.bsky.graph.get_list(params),
            description="fetching source list members",
        )

        items = getattr(resp, "items", None)
        if items is None and isinstance(resp, dict):
            items = resp.get("items", [])

        for item in items or []:
            did = extract_list_member_did(item)
            if did:
                dids.add(did)

        cursor = getattr(resp, "cursor", None)
        if cursor is None and isinstance(resp, dict):
            cursor = resp.get("cursor")
        if not cursor:
            break

    return dids


def _build_starter_pack_record(starter_cfg: dict, source_list_uri: str) -> dict:
    return {
        "$type": "app.bsky.graph.starterpack",
        "name": starter_cfg["name"],
        "description": starter_cfg["description"],
        "list": source_list_uri,
        "createdAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def upsert_starter_pack_record(client, starter_cfg: dict, source_list_uri: str, dry_run: bool):
    """Create/update starter-pack record in the bot's repo."""
    record = _build_starter_pack_record(starter_cfg, source_list_uri)
    repo_did = client.me.did
    rkey = starter_cfg["record_key"]
    at_uri = f"at://{repo_did}/app.bsky.graph.starterpack/{rkey}"

    if dry_run:
        print(f"[DRY-RUN] Would upsert starter-pack record: {at_uri}")
        return at_uri

    resp = retry_network_call(
        lambda: client.com.atproto.repo.put_record(
            {
                "repo": repo_did,
                "collection": "app.bsky.graph.starterpack",
                "rkey": rkey,
                "record": record,
            }
        ),
        description="upserting starter-pack record",
    )
    created_uri = getattr(resp, "uri", None)
    if created_uri is None and isinstance(resp, dict):
        created_uri = resp.get("uri")
    return created_uri or at_uri


def ensure_following_list_members(
    client,
    list_member_dids: set[str],
    dry_run: bool,
    action_delay_seconds: float,
) -> tuple[int, int]:
    """Follow list members not already followed. Returns (already, newly_followed)."""
    following = fetch_paginated_data(client.get_follows, client.me.did)
    already_following = {follow.did for follow in following}

    missing = sorted(did for did in list_member_dids if did not in already_following and did != client.me.did)
    if not missing:
        print("All source-list members are already followed.")
        return len(already_following.intersection(list_member_dids)), 0

    followed_now = 0
    for index, did in enumerate(missing, start=1):
        if dry_run:
            print(f"[DRY-RUN] Would follow list member {did}")
            followed_now += 1
        else:
            retry_network_call(
                lambda current_did=did: client.follow(current_did),
                description=f"following list member {did}",
            )
            print(f"Followed list member {did} ({index}/{len(missing)})")
            followed_now += 1

        if action_delay_seconds > 0 and index < len(missing):
            time.sleep(action_delay_seconds)

    return len(already_following.intersection(list_member_dids)), followed_now


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create/synchronise The Joke Bot starter pack from a source list."
    )
    parser.add_argument(
        "--mode",
        choices=["setup", "sync"],
        default="setup",
        help="setup=upsert starter-pack record + sync follows, sync=follow-only unless config enables record upsert",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    controls = get_runtime_controls()
    dry_run = controls["dry_run"]
    action_delay_seconds = controls["action_delay_seconds"]

    cfg = load_starter_pack_config().get("starter_pack", {})
    if not cfg.get("enabled"):
        print("Starter-pack integration is disabled in resources/jokebot_starter_pack.json.")
        return 0

    source_list_uri = str(cfg.get("source_list_uri") or "").strip()
    if not source_list_uri:
        print("source_list_uri is required in resources/jokebot_starter_pack.json.")
        return 2

    if not source_list_uri.startswith("at://"):
        print("source_list_uri must be a valid at:// URI.")
        return 2

    try:
        client, username = login_client()
        print(f"Authenticated as {username} ({client.me.did})")

        list_member_dids = fetch_list_member_dids(client, source_list_uri)
        print(f"Fetched {len(list_member_dids)} unique member DID(s) from source list.")

        upsert_enabled = bool(cfg.get("sync", {}).get("upsert_record", True))
        follow_enabled = bool(cfg.get("sync", {}).get("follow_list_members", True))

        starter_pack_uri = None
        if args.mode == "setup" or upsert_enabled:
            starter_pack_uri = upsert_starter_pack_record(client, cfg, source_list_uri, dry_run)
            print(f"Starter-pack URI: {starter_pack_uri}")

        already = 0
        followed_now = 0
        if follow_enabled:
            already, followed_now = ensure_following_list_members(
                client,
                list_member_dids,
                dry_run=dry_run,
                action_delay_seconds=action_delay_seconds,
            )

        print(
            "Summary: "
            f"list_members={len(list_member_dids)}, "
            f"already_followed={already}, "
            f"followed_now={followed_now}, "
            f"starter_pack_updated={'yes' if (args.mode == 'setup' or upsert_enabled) else 'no'}."
        )
        return 0
    except (
        ValueError,
        requests.RequestException,
        TimeoutError,
        atproto_client.exceptions.NetworkError,
        atproto_client.exceptions.BadRequestError,
    ) as exc:
        print(f"Starter-pack management failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
