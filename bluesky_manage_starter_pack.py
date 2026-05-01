"""Create/synchronise The Joke Bot starter pack from a configured source list."""

import argparse
import datetime as dt
import json
import pathlib
import re
import time

import atproto_client.exceptions
import requests

from bluesky_common import (
    get_runtime_controls,
    login_client,
    mask_sensitive,
    retry_network_call,
)
from bluesky_follower_utils import fetch_list_member_dids, fetch_paginated_data

_CONFIG_PATH = pathlib.Path(__file__).parent / "resources" / "jokebot_starter_pack.json"
_STARTERPACK_COLLECTION = "app.bsky.graph.starterpack"
_AT_URI_PATTERN = re.compile(r"^at://([^/]+)/([^/]+)/([^/]+)$")


def load_starter_pack_config() -> dict:
    """Load starter-pack config from disk with safe defaults."""
    default = {
        "starter_pack": {
            "enabled": False,
            "name": "The Joke Bot Funnies",
            "description": "Starter pack built from The Joke Bot's Funnies list.",
            "source_list_uri": "",
            "record_key": "",
            "starter_pack_uri": "",
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
                starter.get(
                    "source_list_uri", default["starter_pack"]["source_list_uri"]
                )
            ).strip(),
            "record_key": str(
                starter.get("record_key", default["starter_pack"]["record_key"])
            ).strip(),
            "starter_pack_uri": str(
                starter.get(
                    "starter_pack_uri", default["starter_pack"]["starter_pack_uri"]
                )
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
                sync.get(
                    "upsert_record", default["starter_pack"]["sync"]["upsert_record"]
                )
            ),
        }
    )

    return default


def _build_starter_pack_record(
    starter_cfg: dict, source_list_uri: str, created_at: str | None = None
) -> dict:
    return {
        "$type": "app.bsky.graph.starterpack",
        "name": starter_cfg["name"],
        "description": starter_cfg["description"],
        "list": source_list_uri,
        "createdAt": created_at
        or dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _looks_like_tid(value: str) -> bool:
    # Starter-pack record keys are TIDs. This conservative pattern is enough
    # to distinguish from friendly slug-like keys.
    return bool(re.fullmatch(r"[234567abcdefghijklmnopqrstuvwxyz]{13}", value))


def _parse_at_uri(uri: str) -> dict | None:
    match = _AT_URI_PATTERN.fullmatch(uri.strip())
    if not match:
        return None
    return {
        "did": match.group(1),
        "collection": match.group(2),
        "rkey": match.group(3),
    }


def upsert_starter_pack_record(
    client, starter_cfg: dict, source_list_uri: str, dry_run: bool
):
    """Create/update starter-pack record in the bot's repo."""
    repo_did = client.me.did
    configured_uri = str(starter_cfg.get("starter_pack_uri") or "").strip()
    configured_rkey = str(starter_cfg.get("record_key") or "").strip()

    target_rkey = ""
    target_uri = ""
    use_put_record = False

    if configured_uri:
        parsed_uri = _parse_at_uri(configured_uri)
        if not parsed_uri:
            raise ValueError("starter_pack_uri must be a valid at:// URI.")
        if parsed_uri["did"] != repo_did:
            raise ValueError(
                "starter_pack_uri DID must match the authenticated account DID."
            )
        if parsed_uri["collection"] != _STARTERPACK_COLLECTION:
            raise ValueError("starter_pack_uri must target app.bsky.graph.starterpack.")
        target_rkey = parsed_uri["rkey"]
        target_uri = configured_uri
        use_put_record = True
    elif _looks_like_tid(configured_rkey):
        target_rkey = configured_rkey
        target_uri = f"at://{repo_did}/{_STARTERPACK_COLLECTION}/{target_rkey}"
        use_put_record = True

    if dry_run:
        if use_put_record:
            print(f"[DRY-RUN] Would update starter-pack record: {target_uri}")
            return target_uri
        print("[DRY-RUN] Would create starter-pack record (server-generated TID rkey).")
        return ""

    # Preserve the original createdAt timestamp when updating an existing record.
    existing_created_at = None
    if use_put_record:
        try:
            existing = retry_network_call(
                lambda: client.com.atproto.repo.get_record(
                    {
                        "repo": repo_did,
                        "collection": _STARTERPACK_COLLECTION,
                        "rkey": target_rkey,
                    }
                ),
                description="fetching existing starter-pack record",
            )
            ex_value = getattr(existing, "value", None)
            if ex_value is None and isinstance(existing, dict):
                ex_value = existing.get("value")
            if isinstance(ex_value, dict):
                existing_created_at = ex_value.get("createdAt")
        except Exception:  # noqa: BLE001 — transient or not-found; fall back to current time
            pass

    record = _build_starter_pack_record(
        starter_cfg, source_list_uri, created_at=existing_created_at
    )

    if use_put_record:
        resp = retry_network_call(
            lambda: client.com.atproto.repo.put_record(
                {
                    "repo": repo_did,
                    "collection": _STARTERPACK_COLLECTION,
                    "rkey": target_rkey,
                    "record": record,
                }
            ),
            description="upserting starter-pack record",
        )
    else:
        resp = retry_network_call(
            lambda: client.com.atproto.repo.create_record(
                {
                    "repo": repo_did,
                    "collection": _STARTERPACK_COLLECTION,
                    "record": record,
                }
            ),
            description="creating starter-pack record",
        )

    created_uri = getattr(resp, "uri", None)
    if created_uri is None and isinstance(resp, dict):
        created_uri = resp.get("uri")

    if use_put_record:
        return target_uri

    if created_uri and not use_put_record:
        print(
            "Created starter-pack record with generated URI. "
            "Persist this as starter_pack_uri in resources/jokebot_starter_pack.json "
            "for deterministic future updates."
        )
    return created_uri or target_uri


def ensure_following_list_members(
    client,
    list_member_dids: set[str],
    dry_run: bool,
    action_delay_seconds: float,
) -> tuple[int, int]:
    """Follow list members not already followed. Returns (already, newly_followed)."""
    following = fetch_paginated_data(client.get_follows, client.me.did)
    already_following = {follow.did for follow in following}

    missing = sorted(
        did
        for did in list_member_dids
        if did not in already_following and did != client.me.did
    )
    if not missing:
        print("All source-list members are already followed.")
        return len(already_following.intersection(list_member_dids)), 0

    followed_now = 0
    for index, did in enumerate(missing, start=1):
        masked_did = mask_sensitive(did)
        if dry_run:
            print(f"[DRY-RUN] Would follow list member {masked_did}")
            followed_now += 1
        else:
            retry_network_call(
                lambda current_did=did: client.follow(current_did),
                description=f"following list member {masked_did}",
            )
            print(
                f"Followed list member {masked_did} ({index}/{len(missing)})"
            )
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
        print(
            "Starter-pack integration is disabled in resources/jokebot_starter_pack.json."
        )
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
        print(
            f"Authenticated as {mask_sensitive(username)} ({mask_sensitive(client.me.did)})"
        )

        list_member_dids = fetch_list_member_dids(client, source_list_uri)
        print(f"Fetched {len(list_member_dids)} unique member DID(s) from source list.")

        upsert_enabled = bool(cfg.get("sync", {}).get("upsert_record", True))
        follow_enabled = bool(cfg.get("sync", {}).get("follow_list_members", True))

        starter_pack_uri = None
        if args.mode == "setup" or upsert_enabled:
            starter_pack_uri = upsert_starter_pack_record(
                client, cfg, source_list_uri, dry_run
            )
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
