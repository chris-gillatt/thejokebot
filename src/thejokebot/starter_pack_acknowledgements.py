"""Opt-in, once-per-pack acknowledgements for verified candidate memberships."""

from __future__ import annotations

import base64
import copy
import hashlib
import re
import secrets
from datetime import datetime, timezone

from atproto import models
from atproto_client.exceptions import BadRequestError
from pydantic import BaseModel

from thejokebot import denylist
from thejokebot import state as bot_state
from thejokebot.commands.post_joke import _grapheme_len
from thejokebot.runtime import (
    get_nested_value,
    get_runtime_controls,
    retry_network_call,
)
from thejokebot.starter_pack_membership import PACK_URI, inspect_membership

COLLECTION = "app.bsky.feed.post"
MAX_POSTS = 1
MAX_METRICS_AGE_SECONDS = 48 * 60 * 60
HANDLE = re.compile(r"^[a-zA-Z0-9.-]+$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ledger(state: dict) -> dict:
    ledger = state.get("starter_pack_acknowledgements")
    if (
        not isinstance(ledger, dict)
        or not isinstance(ledger.get("packs"), dict)
        or "baseline_at" not in ledger
    ):
        raise ValueError("Invalid starter-pack acknowledgement ledger")
    return ledger


def baseline_memberships(client, explicit=()) -> dict:
    if get_runtime_controls()["dry_run"]:
        raise ValueError("Dry-run mode forbids saving a starter-pack baseline")
    state = bot_state.load_state()
    report = inspect_membership(client, state, explicit)
    if not report["all_candidates_classified"]:
        raise ValueError("Baseline requires all candidate memberships to be classified")
    if not report["candidate_count"]:
        raise ValueError("Baseline requires at least one known candidate pack")

    def apply(latest):
        ledger = _ledger(latest)
        if ledger["baseline_at"] is not None:
            raise ValueError("Starter-pack baseline is already initialised")
        ledger["baseline_at"] = report["checked_at"]
        for result in report["results"]:
            ledger["packs"][result["pack_uri"]] = {
                "status": "baseline" if result["status"] == "member" else "observed",
                "first_observed_at": report["checked_at"],
            }

    bot_state.update_state(apply, domains="social")
    return report


def _eligible_posts(client, state: dict, metrics: dict) -> list[dict]:
    generated = datetime.fromisoformat(metrics["generated_at"].replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - generated).total_seconds()
    if not 0 <= age <= MAX_METRICS_AGE_SECONDS:
        raise ValueError(
            "Dashboard metrics are stale or future-dated; collect them first"
        )
    bot_did = get_nested_value(client, "me", "did")
    top_posts = metrics.get("top_posts")
    if not isinstance(top_posts, list) or not 1 <= len(top_posts) <= 6:
        raise ValueError("Dashboard must provide one to six top original jokes")
    uris = [post.get("uri") for post in top_posts]
    prefix = f"at://{bot_did}/{COLLECTION}/"
    if any(not isinstance(uri, str) or not uri.startswith(prefix) for uri in uris):
        raise ValueError("Dashboard top jokes must belong to the authenticated bot")
    payload = denylist.load_denylist()
    excluded = {entry.get("source_post_uri") for entry in payload["jokes"]}
    excluded |= bot_state.get_deleted_post_uris(copy.deepcopy(state))
    banned_text = denylist.get_denylisted_b64s(payload)
    history = bot_state.get_post_uri_index(state)
    response = retry_network_call(
        lambda: client.app.bsky.feed.get_posts({"uris": uris}),
        description="verifying popular original jokes",
    )
    posts = get_nested_value(response, "posts")
    if not isinstance(posts, list):
        raise ValueError("Popular-joke response has no post array")
    eligible = []
    for post in posts:
        uri = get_nested_value(post, "uri")
        if uri not in uris or uri not in history or uri in excluded:
            continue
        text = get_nested_value(post, "record", "text")
        cid = get_nested_value(post, "cid")
        if (
            get_nested_value(post, "author", "did") != bot_did
            or get_nested_value(post, "record", "reply") is not None
            or get_nested_value(post, "record", "embed") is not None
            or not isinstance(text, str)
            or not isinstance(cid, str)
            or not cid
        ):
            continue
        encoded = base64.b64encode(text.split("\n\n#")[0].encode()).decode()
        if encoded in banned_text or history[uri].get("b64") in banned_text:
            continue
        eligible.append({"uri": uri, "cid": cid})
    if not eligible:
        raise ValueError("No currently accessible, unmoderated top-six original joke")
    return eligible


def _proposal(client, pack_uri: str, joke: dict) -> dict:
    response = retry_network_call(
        lambda: client.app.bsky.graph.get_starter_pack({"starterPack": pack_uri}),
        description="verifying starter-pack creator",
    )
    pack = get_nested_value(response, "starter_pack") or get_nested_value(
        response, "starterPack"
    )
    creator = pack_uri.split("/")[2]
    if (
        not creator.startswith("did:")
        or get_nested_value(pack, "uri") != pack_uri
        or get_nested_value(pack, "creator", "did") != creator
    ):
        raise ValueError("Starter-pack creator identity could not be verified")
    profile = retry_network_call(
        lambda: client.app.bsky.actor.get_profile({"actor": creator}),
        description="resolving starter-pack creator handle",
    )
    handle = get_nested_value(profile, "handle")
    if (
        get_nested_value(profile, "did") != creator
        or not isinstance(handle, str)
        or not HANDLE.fullmatch(handle)
    ):
        raise ValueError("Starter-pack creator has no verified current handle")
    mention = f"@{handle}"
    link = f"https://bsky.app/starter-pack/{creator}/{pack_uri.rsplit('/', 1)[-1]}"
    text = (
        f"Thanks {mention} for including me in your starter pack! "
        f"Here's one of my popular jokes, just for you.\n\n{link}"
    )
    if _grapheme_len(text) > 300:
        raise ValueError("Starter-pack thank-you exceeds the Bluesky post length limit")
    start = len("Thanks ".encode())
    link_start = len(text[: text.index(link)].encode())
    record = {
        "$type": COLLECTION,
        "text": text,
        "createdAt": _now(),
        "facets": [
            {
                "index": {"byteStart": start, "byteEnd": start + len(mention.encode())},
                "features": [
                    {"$type": "app.bsky.richtext.facet#mention", "did": creator}
                ],
            },
            {
                "index": {"byteStart": link_start, "byteEnd": len(text.encode())},
                "features": [{"$type": "app.bsky.richtext.facet#link", "uri": link}],
            },
        ],
        "embed": {"$type": "app.bsky.embed.record", "record": joke},
    }
    record = models.AppBskyFeedPost.Record.model_validate(record).model_dump(
        by_alias=True, exclude_none=True
    )
    rkey = "starter-pack-" + hashlib.sha256(pack_uri.encode()).hexdigest()
    return {
        "pack_uri": pack_uri,
        "creator_did": creator,
        "rkey": rkey,
        "record": record,
    }


def preview_acknowledgements(client, metrics: dict, explicit=()) -> dict:
    state = bot_state.load_state()
    ledger = _ledger(state)
    if ledger["baseline_at"] is None:
        raise ValueError("Initialise the no-thank-you baseline before previewing")
    report = inspect_membership(client, state, explicit)
    proposals = []
    for result in report["results"]:
        uri = result["pack_uri"]
        entry = ledger["packs"].get(uri, {})
        if (
            result["status"] != "member"
            or entry.get("status") in ("baseline", "published")
            or uri.split("/")[2] == get_nested_value(client, "me", "did")
        ):
            continue
        if entry.get("status") == "pending":
            proposals.append(copy.deepcopy(entry["proposal"]))
        else:
            jokes = _eligible_posts(client, state, metrics)
            proposals.append(_proposal(client, uri, secrets.choice(jokes)))
        if len(proposals) >= MAX_POSTS:
            break
    return {"membership": report, "proposals": proposals, "live_posting_enabled": False}


def _record_at_key(client, rkey: str):
    try:
        return retry_network_call(
            lambda: client.com.atproto.repo.get_record(
                {"repo": client.me.did, "collection": COLLECTION, "rkey": rkey}
            ),
            description="reconciling starter-pack acknowledgement receipt",
        )
    except BadRequestError as exc:
        if (
            get_nested_value(exc, "response", "status_code") == 400
            and get_nested_value(exc, "response", "content", "error")
            == "RecordNotFound"
        ):
            return None
        raise


def _verify_receipt(client, response, proposal: dict) -> tuple[str, str]:
    expected = f"at://{client.me.did}/{COLLECTION}/{proposal['rkey']}"
    uri = get_nested_value(response, "uri")
    cid = get_nested_value(response, "cid")
    value = get_nested_value(response, "value")
    if isinstance(value, BaseModel):
        value = value.model_dump(by_alias=True, exclude_none=True)
    if isinstance(value, dict):
        value = models.AppBskyFeedPost.Record.model_validate(value).model_dump(
            by_alias=True, exclude_none=True
        )
    if (
        not isinstance(uri, str)
        or uri != expected
        or not isinstance(cid, str)
        or not cid
        or value != proposal["record"]
    ):
        raise ValueError(
            "Existing acknowledgement record does not match its saved intent"
        )
    return uri, cid


def _revalidate_intent(client, intent: dict) -> None:
    state = bot_state.load_state()
    pack_uri = intent["pack_uri"]
    report = inspect_membership(client, state, [pack_uri])
    if not report["results"] or report["results"][0]["status"] != "member":
        raise ValueError("Membership is no longer verified; acknowledgement withheld")
    joke = intent["record"]["embed"]["record"]
    fresh = _proposal(client, pack_uri, joke)
    if fresh["creator_did"] == client.me.did:
        raise ValueError("The bot cannot acknowledge its own starter pack")
    fresh["record"]["createdAt"] = intent["record"]["createdAt"]
    if fresh != intent:
        raise ValueError(
            "Acknowledgement preview is stale or has been altered; preview again"
        )
    metrics = {
        "generated_at": intent["record"]["createdAt"],
        "top_posts": [{"uri": joke["uri"]}],
    }
    current = _eligible_posts(client, state, metrics)
    if not any(
        post["uri"] == joke["uri"] and post["cid"] == joke["cid"] for post in current
    ):
        raise ValueError("Quoted joke changed, disappeared or was moderated; withheld")


def _prepare_intent(latest: dict, proposal: dict) -> dict:
    pack_uri = proposal["pack_uri"]
    ledger = _ledger(latest)
    if ledger["baseline_at"] is None:
        raise ValueError("Acknowledgements require an initialised baseline")
    existing = ledger["packs"].get(pack_uri, {})
    if existing.get("status") in ("baseline", "published"):
        raise ValueError("Pack is baselined or already acknowledged")
    if existing.get("status") != "pending":
        existing = {"status": "pending", "proposal": copy.deepcopy(proposal)}
        ledger["packs"][pack_uri] = existing
    return copy.deepcopy(existing["proposal"])


def publish_acknowledgement(client, proposal: dict) -> dict:
    if get_runtime_controls()["dry_run"]:
        raise ValueError(
            "Dry-run mode forbids publishing starter-pack acknowledgements"
        )
    pack_uri = proposal["pack_uri"]
    if not PACK_URI.fullmatch(pack_uri):
        raise ValueError("Invalid acknowledgement pack URI")
    intent = bot_state.update_state(
        lambda latest: _prepare_intent(latest, proposal), domains="social"
    )
    existing = _record_at_key(client, intent["rkey"])
    if existing is None:
        _revalidate_intent(client, intent)
        commit = retry_network_call(
            lambda: client.com.atproto.sync.get_latest_commit({"did": client.me.did}),
            description="reading repository revision before acknowledgement",
        )
        cid = get_nested_value(commit, "cid")
        if not isinstance(cid, str) or not cid:
            raise ValueError(
                "Could not verify repository revision before acknowledgement"
            )
        if _record_at_key(client, intent["rkey"]) is not None:
            raise ValueError(
                "Acknowledgement appeared concurrently; reconcile next run"
            )
        client.com.atproto.repo.create_record(
            {
                "repo": client.me.did,
                "collection": COLLECTION,
                "rkey": intent["rkey"],
                "record": intent["record"],
                "swapCommit": cid,
            }
        )
        existing = _record_at_key(client, intent["rkey"])
    uri, cid = _verify_receipt(client, existing, intent)

    def confirm(latest):
        _ledger(latest)["packs"][pack_uri].update(
            status="published", post_uri=uri, post_cid=cid, confirmed_at=_now()
        )

    bot_state.update_state(confirm, domains="social")
    return {"pack_uri": pack_uri, "post_uri": uri, "post_cid": cid}
