"""Create and reconcile follow records without duplicating ambiguous writes."""

import copy
import hashlib
from datetime import datetime, timezone

from atproto import models
from atproto_client.exceptions import BadRequestError

from thejokebot import state as bot_state
from thejokebot import state_transactions
from thejokebot.runtime import get_nested_value, retry_network_call

_COLLECTION = "app.bsky.graph.follow"
_TID_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"
_GRACE_SOURCES = {"interaction": "interaction", "discovery": "follow_fellows"}
_FOLLOW_SOURCES = {"followback", *_GRACE_SOURCES, "starter_pack"}


def _follow_rkey(did: str) -> str:
    digest = hashlib.sha256(did.encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)
    encoded = ["2"] * 13
    for index in range(12, -1, -1):
        value, digit = divmod(value, len(_TID_ALPHABET))
        encoded[index] = _TID_ALPHABET[digit]
    return "".join(encoded)


def _build_intent(repo_did: str, did: str, source: str) -> dict:
    record = models.AppBskyGraphFollow.Record(
        subject=did,
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    ).model_dump(by_alias=True, exclude_none=True)
    rkey = _follow_rkey(did)
    return {
        "rkey": rkey,
        "uri": f"at://{repo_did}/{_COLLECTION}/{rkey}",
        "record": record,
        "source": source,
    }


def _prepare_intent(latest: dict, repo_did: str, did: str, source: str) -> dict:
    pending = latest.setdefault("follow_tracking", {}).setdefault("pending_follows", {})
    existing = pending.get(did)
    if existing is not None:
        if (
            not isinstance(existing, dict)
            or not isinstance(existing.get("record"), dict)
            or existing.get("source") not in _FOLLOW_SOURCES
            or existing.get("rkey") != _follow_rkey(did)
            or existing.get("uri")
            != f"at://{repo_did}/{_COLLECTION}/{existing.get('rkey')}"
            or existing["record"].get("subject") != did
            or existing["record"].get("$type") != _COLLECTION
        ):
            raise ValueError("Invalid pending follow intent")
        return copy.deepcopy(existing)

    intent = _build_intent(repo_did, did, source)
    pending[did] = intent
    return intent


def _record_at_key(client, repo_did: str, intent: dict):
    try:
        return retry_network_call(
            lambda: client.com.atproto.repo.get_record(
                {
                    "repo": repo_did,
                    "collection": _COLLECTION,
                    "rkey": intent["rkey"],
                }
            ),
            description="reconciling follow record",
        )
    except BadRequestError as exc:
        if (
            get_nested_value(exc, "response", "status_code") == 400
            and get_nested_value(exc, "response", "content", "error")
            == "RecordNotFound"
        ):
            return None
        raise


def _normalise_follow_record(value) -> dict:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        value = model_dump(by_alias=True, exclude_none=True)
    if not isinstance(value, dict):
        raise ValueError("Follow record receipt has an unexpected value")
    try:
        return models.AppBskyGraphFollow.Record.model_validate(value).model_dump(
            by_alias=True, exclude_none=True
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Follow record receipt is malformed") from exc


def _verify_record_response(response, intent: dict) -> None:
    uri = get_nested_value(response, "uri")
    cid = get_nested_value(response, "cid")
    if uri != intent["uri"] or not isinstance(cid, str) or not cid:
        raise ValueError("Follow record receipt does not match its saved intent")
    value = get_nested_value(response, "value")
    if value is not None and _normalise_follow_record(value) != intent["record"]:
        raise ValueError("Follow record receipt does not match its saved intent")


def _verify_existing_record(response, intent: dict) -> None:
    _verify_record_response(response, intent)
    if get_nested_value(response, "value") is None:
        raise ValueError("Existing follow record receipt has no value")


def _checkpoint_follow(state: dict, did: str, intent: dict) -> None:
    def apply(latest: dict) -> None:
        pending = latest.setdefault("follow_tracking", {}).setdefault(
            "pending_follows", {}
        )
        current = pending.get(did)
        if current is None:
            return
        if current != intent:
            raise ValueError("Pending follow intent changed during reconciliation")
        del pending[did]
        if intent["source"] in bot_state.ACQUISITION_COHORT_SOURCES:
            bot_state.record_acquisition(latest, did, intent["source"])
        grace_source = _GRACE_SOURCES.get(intent["source"])
        if grace_source is not None:
            bot_state.record_follow_grace(latest, did, source=grace_source)
            bot_state.prune_follow_grace(latest)

    state_transactions.apply(state, apply, domains="social")


def follow_account(client, state: dict | None, did: str, source: str) -> bool:
    """Follow once, retaining a verifiable intent across ambiguous outcomes."""
    repo_did = client.me.did
    if source not in _FOLLOW_SOURCES:
        raise ValueError(f"Unknown follow source: {source}")

    if state is None:
        state = bot_state.load_state()
    intent = bot_state.update_state(
        lambda latest: _prepare_intent(latest, repo_did, did, source),
        domains="social",
    )
    state.setdefault("follow_tracking", {}).setdefault("pending_follows", {})[did] = (
        copy.deepcopy(intent)
    )

    existing = _record_at_key(client, repo_did, intent)
    if existing is not None:
        _verify_existing_record(existing, intent)
        _checkpoint_follow(state, did, intent)
        return True

    record = models.AppBskyGraphFollow.Record.model_validate(intent["record"])
    try:
        response = client.app.bsky.graph.follow.create(
            repo=repo_did,
            record=record,
            rkey=intent["rkey"],
        )
    except Exception as create_error:
        try:
            existing = _record_at_key(client, repo_did, intent)
        except Exception:
            raise create_error
        if existing is None:
            raise
        _verify_existing_record(existing, intent)
    else:
        response = {
            "uri": get_nested_value(response, "uri"),
            "cid": get_nested_value(response, "cid"),
            "value": intent["record"],
        }
        _verify_record_response(response, intent)

    _checkpoint_follow(state, did, intent)
    return True


def reconcile_pending_follows(client, state: dict) -> None:
    """Confirm accepted follow writes whose local checkpoint did not complete."""
    latest = bot_state.load_state()
    pending = copy.deepcopy(
        latest.get("follow_tracking", {}).get("pending_follows", {})
    )
    state.setdefault("follow_tracking", {})["pending_follows"] = copy.deepcopy(pending)
    for did, intent in pending.items():
        existing = _record_at_key(client, client.me.did, intent)
        if existing is None:
            continue
        _verify_existing_record(existing, intent)
        _checkpoint_follow(state, did, intent)
