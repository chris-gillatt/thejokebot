"""Read-only membership checks for known candidate starter packs, not global discovery."""

import re
import time
from datetime import datetime, timezone

import atproto_client.exceptions
import requests

from thejokebot.runtime import get_nested_value, retry_network_call

MAX_PACKS = 20
MAX_LIST_PAGES = 10
MAX_RUNTIME_SECONDS = 60
PAGE_LIMIT = 100
PACK_URI = re.compile(r"^at://[^/\s]+/app\.bsky\.graph\.starterpack/[^/?#\s]+$")
LIST_URI = re.compile(r"^at://[^/\s]+/app\.bsky\.graph\.list/[^/?#\s]+$")


class _BudgetExpired(RuntimeError):
    pass


def _read(operation, deadline, description):
    def guarded():
        if time.monotonic() >= deadline:
            raise _BudgetExpired()
        return operation()

    return retry_network_call(guarded, description=description)


def candidate_uris(state, explicit=()):
    if any(not PACK_URI.fullmatch(uri) for uri in explicit):
        raise ValueError("Explicit candidates must be canonical starter-pack AT URIs")
    packs = (
        get_nested_value(state, "follow_tracking", "starter_pack_attribution", "packs")
        or {}
    )
    valid = [uri for uri in packs if isinstance(uri, str) and PACK_URI.fullmatch(uri)]
    return list(dict.fromkeys([*explicit, *sorted(valid)])), len(packs) - len(valid)


def _list_uri(pack, expected_uri):
    if get_nested_value(pack, "uri") != expected_uri:
        raise ValueError("Starter-pack response URI mismatch")
    hydrated = get_nested_value(pack, "list", "uri")
    recorded = get_nested_value(pack, "record", "list")
    if hydrated and recorded and hydrated != recorded:
        raise ValueError("Starter-pack list references disagree")
    uri = hydrated or recorded
    if not isinstance(uri, str) or not LIST_URI.fullmatch(uri):
        raise ValueError("Starter pack has no valid underlying list")
    return uri


def _walk_list(client, list_uri, actor_did, deadline, result):
    cursor = None
    seen = set()
    for page in range(MAX_LIST_PAGES):
        if time.monotonic() >= deadline:
            return "unknown", "runtime_limit"
        params = {"list": list_uri, "limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        response = _read(
            lambda current_params=params: client.app.bsky.graph.get_list(
                current_params
            ),
            deadline,
            "checking candidate starter-pack list",
        )
        result["pages_checked"] = page + 1
        if get_nested_value(response, "list", "uri") != list_uri:
            raise ValueError("List response URI mismatch")
        items = get_nested_value(response, "items")
        if not isinstance(items, list):
            raise ValueError("List response has no member array")
        dids = [get_nested_value(item, "subject", "did") for item in items]
        if actor_did in dids:
            return "member", "member_observed"
        if any(not isinstance(did, str) or not did.startswith("did:") for did in dids):
            raise ValueError("List response contains an invalid member")
        cursor = get_nested_value(response, "cursor")
        if not cursor:
            return "not_member", "complete_list"
        if not isinstance(cursor, str) or cursor in seen:
            return "unknown", "invalid_or_repeated_cursor"
        seen.add(cursor)
    return "unknown", "page_limit"


def _inspect_pack(client, uri, actor_did, deadline):
    result = {"pack_uri": uri, "status": "unknown", "pages_checked": 0}
    try:
        response = _read(
            lambda: client.app.bsky.graph.get_starter_pack({"starterPack": uri}),
            deadline,
            "reading candidate starter pack",
        )
        pack = get_nested_value(response, "starter_pack") or get_nested_value(
            response, "starterPack"
        )
        list_uri = _list_uri(pack, uri)
        result["list_uri"] = list_uri
        result["status"], result["reason"] = _walk_list(
            client, list_uri, actor_did, deadline, result
        )
    except _BudgetExpired:
        result["reason"] = "runtime_limit"
    except (
        requests.RequestException,
        TimeoutError,
        atproto_client.exceptions.AtProtocolError,
        ValueError,
    ) as exc:
        result["reason"] = f"read_failed:{type(exc).__name__}"
    return result


def inspect_membership(client, state, explicit=()):
    actor_did = get_nested_value(client, "me", "did")
    if not isinstance(actor_did, str) or not actor_did.startswith("did:"):
        raise ValueError("Authenticated account DID is required")
    candidates, invalid = candidate_uris(state, explicit)
    deadline = time.monotonic() + MAX_RUNTIME_SECONDS
    results = []
    for uri in candidates[:MAX_PACKS]:
        if time.monotonic() >= deadline:
            break
        results.append(_inspect_pack(client, uri, actor_did, deadline))
    counts = {
        status: sum(result["status"] == status for result in results)
        for status in ("member", "not_member", "unknown")
    }
    not_checked = len(candidates) - len(results)
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "scope": "retained_attributed_follow_packs_and_explicit_candidates_only",
        "complete_reverse_lookup": False,
        "inclusion_dates_known": False,
        "candidate_count": len(candidates),
        "invalid_candidates": invalid,
        "not_checked": not_checked,
        "all_candidates_classified": not_checked == 0
        and counts["unknown"] == 0
        and invalid == 0,
        "counts": counts,
        "results": results,
    }
