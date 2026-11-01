"""Starter-pack thanks must remain opt-in, receipt-backed and once per pack."""

import base64
import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

import pytest
from atproto_client.exceptions import BadRequestError
from atproto_client.request import Response

from thejokebot import starter_pack_acknowledgements as acknowledgements
from thejokebot import starter_pack_membership as membership
from thejokebot import state as bot_state
from thejokebot.commands import acknowledge_starter_packs as command

BOT = "did:plc:bot"
CREATOR = "did:plc:creator"
PACK = f"at://{CREATOR}/app.bsky.graph.starterpack/pack"
LIST = f"at://{CREATOR}/app.bsky.graph.list/list"
JOKE = f"at://{BOT}/app.bsky.feed.post/joke"
CID = "bafyreie5nqv6kd3qnfjug7ix6lvfrvi3e7ogvdmdcb3hlcpyh6m7vmvrn4"


def missing():
    return BadRequestError(Response(False, 400, {"error": "RecordNotFound"}, {}))


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv("BLUESKY_DRY_RUN", "false")
    monkeypatch.setattr(bot_state, "STATE_FILE", str(tmp_path / "bot_state.json"))
    monkeypatch.setattr(
        acknowledgements, "retry_network_call", lambda fn, description: fn()
    )
    monkeypatch.setattr(membership, "retry_network_call", lambda fn, description: fn())
    client = mock.Mock()
    client.me.did = BOT
    client.app.bsky.graph.get_starter_pack.return_value = {
        "starterPack": {
            "uri": PACK,
            "creator": {"did": CREATOR},
            "record": {"list": LIST},
        }
    }
    client.app.bsky.graph.get_list.return_value = {
        "list": {"uri": LIST},
        "items": [{"subject": {"did": BOT}}],
    }
    client.app.bsky.actor.get_profile.return_value = {
        "did": CREATOR,
        "handle": "new-handle.bsky.social",
    }
    client.app.bsky.feed.get_posts.return_value = {
        "posts": [
            {
                "uri": JOKE,
                "cid": CID,
                "author": {"did": BOT},
                "record": {"text": "A popular joke.\n\n#joke"},
            }
        ]
    }
    client.com.atproto.sync.get_latest_commit.return_value = {"cid": CID}
    state = bot_state._default_state()
    state["starter_pack_acknowledgements"]["baseline_at"] = "2026-10-01T00:00:00Z"
    state["follow_tracking"]["starter_pack_attribution"]["packs"] = {PACK: {}}
    bot_state.add_posted_joke(
        state,
        base64.b64encode(b"A popular joke.").decode(),
        "jokeapi",
        post_uri=JOKE,
        post_cid=CID,
    )
    bot_state.save_state(state, domains=("posting", "social", "moderation"))
    denied = {"jokes": []}
    monkeypatch.setattr(acknowledgements.denylist, "load_denylist", lambda: denied)
    metrics = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "top_posts": [{"uri": JOKE}],
    }
    return SimpleNamespace(client=client, metrics=metrics, denied=denied, root=tmp_path)


def preview(env):
    return acknowledgements.preview_acknowledgements(env.client, env.metrics)


def receipt(proposal, value=None):
    return {
        "uri": f"at://{BOT}/app.bsky.feed.post/{proposal['rkey']}",
        "cid": CID,
        "value": proposal["record"] if value is None else value,
    }


def test_preview_resolves_handle_uses_fresh_cid_and_writes_nothing(environment):
    before = bot_state.load_state()
    report = preview(environment)
    assert report["live_posting_enabled"] is False
    proposal = report["proposals"][0]
    record = proposal["record"]
    assert record["embed"]["record"]["uri"] == JOKE
    assert record["embed"]["record"]["cid"] == CID
    assert "popular jokes" in record["text"]
    assert "@new-handle.bsky.social" in record["text"]
    raw = record["text"].encode()
    for facet in record["facets"]:
        fragment = raw[facet["index"]["byteStart"] : facet["index"]["byteEnd"]].decode()
        feature = facet["features"][0]
        if feature["$type"].endswith("#mention"):
            assert fragment == "@new-handle.bsky.social"
            assert feature["did"] == CREATOR
        else:
            assert fragment == feature["uri"]
            assert feature["uri"] == f"https://bsky.app/starter-pack/{CREATOR}/pack"
    assert bot_state.load_state() == before
    environment.client.com.atproto.repo.create_record.assert_not_called()
    environment.client.send_post.assert_not_called()


def test_baseline_memberships_are_never_thanked_even_after_removal_readdition(
    environment,
):
    bot_state.update_state(
        lambda state: state["starter_pack_acknowledgements"].update(baseline_at=None),
        domains="social",
    )
    acknowledgements.baseline_memberships(environment.client)
    assert preview(environment)["proposals"] == []
    environment.client.app.bsky.graph.get_list.return_value["items"] = []
    assert preview(environment)["proposals"] == []
    environment.client.app.bsky.graph.get_list.return_value["items"] = [
        {"subject": {"did": BOT}}
    ]
    assert preview(environment)["proposals"] == []
    with pytest.raises(ValueError, match="already initialised"):
        acknowledgements.baseline_memberships(environment.client)


def test_baseline_absence_can_be_thanked_on_later_observed_membership(environment):
    bot_state.update_state(
        lambda state: state["starter_pack_acknowledgements"].update(baseline_at=None),
        domains="social",
    )
    environment.client.app.bsky.graph.get_list.return_value["items"] = []
    acknowledgements.baseline_memberships(environment.client)
    environment.client.app.bsky.graph.get_list.return_value["items"] = [
        {"subject": {"did": BOT}}
    ]
    assert len(preview(environment)["proposals"]) == 1


@pytest.mark.parametrize("mode", ["unknown", "empty"])
def test_incomplete_or_empty_baseline_does_not_write(environment, mode):
    if mode == "unknown":
        environment.client.app.bsky.graph.get_list.return_value["items"] = []
        environment.client.app.bsky.graph.get_list.return_value["cursor"] = "same"
    else:
        bot_state.update_state(
            lambda state: state["follow_tracking"]["starter_pack_attribution"].update(
                packs={}
            ),
            domains="social",
        )
    before = bot_state.load_state()
    with pytest.raises(ValueError, match="Baseline requires"):
        acknowledgements.baseline_memberships(environment.client)
    assert bot_state.load_state() == before


@pytest.mark.parametrize("age", [-60, 48 * 3600 + 60])
def test_stale_or_future_metrics_are_rejected(environment, age):
    environment.metrics["generated_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=age)
    ).isoformat()
    with pytest.raises(ValueError, match="stale or future"):
        preview(environment)


@pytest.mark.parametrize("mode", ["not_member", "unknown", "own_pack"])
def test_unverified_memberships_and_own_pack_have_no_proposals(environment, mode):
    if mode == "not_member":
        environment.client.app.bsky.graph.get_list.return_value["items"] = []
    elif mode == "unknown":
        environment.client.app.bsky.graph.get_list.side_effect = TimeoutError("offline")
    else:
        own_pack = PACK.replace(CREATOR, BOT)
        environment.client.app.bsky.graph.get_starter_pack.return_value["starterPack"][
            "uri"
        ] = own_pack
        bot_state.update_state(
            lambda state: state["follow_tracking"]["starter_pack_attribution"].update(
                packs={own_pack: {}}
            ),
            domains="social",
        )
    assert preview(environment)["proposals"] == []


@pytest.mark.parametrize(
    "mode", ["no_baseline", "bad_ledger", "empty_top", "wrong_owner"]
)
def test_invalid_inputs_fail_explicitly(environment, mode):
    if mode == "no_baseline":
        bot_state.update_state(
            lambda state: state["starter_pack_acknowledgements"].update(
                baseline_at=None
            ),
            domains="social",
        )
    elif mode == "bad_ledger":
        bot_state.update_state(
            lambda state: state["starter_pack_acknowledgements"].update(packs=[]),
            domains="social",
        )
    elif mode == "empty_top":
        environment.metrics["top_posts"] = []
    else:
        environment.metrics["top_posts"][0]["uri"] = JOKE.replace(BOT, CREATOR)
    with pytest.raises(ValueError):
        preview(environment)


@pytest.mark.parametrize(
    "mode",
    [
        "missing",
        "wrong_author",
        "no_cid",
        "reply",
        "quote",
        "unknown_original",
        "denied_uri",
        "denied_text",
        "deleted",
    ],
)
def test_missing_moderated_or_nonoriginal_jokes_are_excluded(environment, mode):
    post = environment.client.app.bsky.feed.get_posts.return_value["posts"][0]
    if mode == "missing":
        environment.client.app.bsky.feed.get_posts.return_value["posts"] = []
    elif mode == "wrong_author":
        post["author"]["did"] = CREATOR
    elif mode == "no_cid":
        post["cid"] = None
    elif mode in ("reply", "quote"):
        post["record"]["reply" if mode == "reply" else "embed"] = {}
    elif mode == "unknown_original":
        bot_state.update_state(
            lambda state: state.update(posted_jokes=[]), domains="posting"
        )
    elif mode == "denied_uri":
        environment.denied["jokes"] = [{"source_post_uri": JOKE}]
    elif mode == "denied_text":
        environment.denied["jokes"] = [
            {"b64": base64.b64encode(b"A popular joke.").decode()}
        ]
    else:
        bot_state.update_state(
            lambda state: state["reports"].update(deleted_post_uris=[JOKE]),
            domains="moderation",
        )
    with pytest.raises(ValueError, match="No currently accessible"):
        preview(environment)


@pytest.mark.parametrize(
    "mode",
    ["pack_mismatch", "creator_mismatch", "profile_mismatch", "handle", "too_long"],
)
def test_identity_and_length_fail_closed(environment, mode):
    pack = environment.client.app.bsky.graph.get_starter_pack.return_value[
        "starterPack"
    ]
    profile = environment.client.app.bsky.actor.get_profile.return_value
    if mode == "pack_mismatch":
        environment.client.app.bsky.graph.get_starter_pack.side_effect = [
            copy.deepcopy({"starterPack": pack}),
            {"starterPack": {**pack, "uri": PACK + "wrong"}},
        ]
    elif mode == "creator_mismatch":
        pack["creator"]["did"] = BOT
    elif mode == "profile_mismatch":
        profile["did"] = BOT
    else:
        profile["handle"] = "bad handle" if mode == "handle" else "x" * 300
    with pytest.raises(ValueError):
        preview(environment)


def test_per_run_cap_is_one_and_sdk_models_are_supported(environment):
    post = environment.client.app.bsky.feed.get_posts.return_value["posts"][0]
    environment.client.app.bsky.feed.get_posts.return_value = SimpleNamespace(
        posts=[
            SimpleNamespace(
                uri=post["uri"],
                cid=post["cid"],
                author=SimpleNamespace(did=BOT),
                record=SimpleNamespace(
                    text=post["record"]["text"], reply=None, embed=None
                ),
            )
        ]
    )
    assert len(preview(environment)["proposals"]) == acknowledgements.MAX_POSTS == 1


def test_two_verified_memberships_still_propose_only_one_thank_you(environment):
    second = PACK + "2"
    bot_state.update_state(
        lambda state: state["follow_tracking"]["starter_pack_attribution"].update(
            packs={PACK: {}, second: {}}
        ),
        domains="social",
    )
    environment.client.app.bsky.graph.get_starter_pack.side_effect = lambda params: {
        "starterPack": {
            "uri": params["starterPack"],
            "creator": {"did": CREATOR},
            "record": {"list": LIST},
        }
    }
    report = preview(environment)
    assert report["membership"]["counts"]["member"] == 2
    assert len(report["proposals"]) == 1


def test_expired_unsent_preview_is_withheld_but_existing_receipt_can_recover(
    environment,
):
    proposal = preview(environment)["proposals"][0]
    proposal["record"]["createdAt"] = (
        datetime.now(timezone.utc) - timedelta(days=3)
    ).isoformat()
    environment.client.com.atproto.repo.get_record.side_effect = [missing()]
    with pytest.raises(ValueError, match="stale or future"):
        acknowledgements.publish_acknowledgement(environment.client, proposal)
    environment.client.com.atproto.repo.create_record.assert_not_called()
    environment.client.com.atproto.repo.get_record.side_effect = None
    environment.client.com.atproto.repo.get_record.return_value = receipt(proposal)
    acknowledgements.publish_acknowledgement(environment.client, proposal)
    assert (
        bot_state.load_state()["starter_pack_acknowledgements"]["packs"][PACK]["status"]
        == "published"
    )


def test_success_persists_intent_before_write_and_confirms_exact_record(environment):
    proposal = preview(environment)["proposals"][0]
    environment.client.com.atproto.repo.get_record.side_effect = [
        missing(),
        missing(),
        receipt(proposal),
    ]

    def create(data):
        entry = bot_state.load_state()["starter_pack_acknowledgements"]["packs"][PACK]
        assert entry["status"] == "pending"
        assert entry["proposal"] == proposal
        assert data["record"] == proposal["record"]
        assert data["swapCommit"] == CID
        assert data["rkey"] == proposal["rkey"]

    environment.client.com.atproto.repo.create_record.side_effect = create
    result = acknowledgements.publish_acknowledgement(environment.client, proposal)
    entry = bot_state.load_state()["starter_pack_acknowledgements"]["packs"][PACK]
    assert entry["status"] == "published"
    assert entry["post_uri"] == result["post_uri"]
    assert preview(environment)["proposals"] == []
    with pytest.raises(ValueError, match="already acknowledged"):
        acknowledgements.publish_acknowledgement(environment.client, proposal)
    assert environment.client.com.atproto.repo.create_record.call_count == 1


def test_ambiguous_write_recovers_without_resending_or_changing_intent(environment):
    proposal = preview(environment)["proposals"][0]
    environment.client.com.atproto.repo.get_record.side_effect = [missing(), missing()]
    environment.client.com.atproto.repo.create_record.side_effect = TimeoutError(
        "uncertain"
    )
    with pytest.raises(TimeoutError):
        acknowledgements.publish_acknowledgement(environment.client, proposal)
    assert preview(environment)["proposals"] == [proposal]
    environment.client.com.atproto.repo.get_record.side_effect = None
    environment.client.com.atproto.repo.get_record.return_value = receipt(proposal)
    changed = copy.deepcopy(proposal)
    changed["record"]["text"] = "Do not replace the original intent"
    acknowledgements.publish_acknowledgement(environment.client, changed)
    assert environment.client.com.atproto.repo.create_record.call_count == 1
    assert (
        bot_state.load_state()["starter_pack_acknowledgements"]["packs"][PACK]["status"]
        == "published"
    )


@pytest.mark.parametrize(
    "error",
    [
        BadRequestError(Response(False, 400, {"error": "InvalidRequest"}, {})),
        BadRequestError(Response(False, 401, {"error": "RecordNotFound"}, {})),
        TimeoutError("read unavailable"),
    ],
)
def test_unverified_absence_never_sends(environment, error):
    proposal = preview(environment)["proposals"][0]
    environment.client.com.atproto.repo.get_record.side_effect = error
    with pytest.raises(type(error)):
        acknowledgements.publish_acknowledgement(environment.client, proposal)
    environment.client.com.atproto.repo.create_record.assert_not_called()


@pytest.mark.parametrize(
    "mode",
    [
        "mismatch",
        "missing_after_write",
        "concurrent",
        "stale_cid",
        "removed",
        "changed_handle",
        "denied",
        "missing_commit",
    ],
)
def test_publish_withholds_on_conflicts_or_invalid_evidence(environment, mode):
    proposal = preview(environment)["proposals"][0]
    environment.client.com.atproto.repo.get_record.side_effect = [
        missing(),
        missing(),
        missing(),
    ]
    if mode == "mismatch":
        environment.client.com.atproto.repo.get_record.side_effect = [
            receipt(proposal, {**proposal["record"], "text": "Different record"})
        ]
    elif mode == "concurrent":
        environment.client.com.atproto.repo.get_record.side_effect = [
            missing(),
            receipt(proposal),
        ]
    elif mode == "stale_cid":
        environment.client.app.bsky.feed.get_posts.return_value["posts"][0]["cid"] = (
            "changed"
        )
    elif mode == "removed":
        environment.client.app.bsky.graph.get_list.return_value["items"] = []
    elif mode == "changed_handle":
        environment.client.app.bsky.actor.get_profile.return_value["handle"] = (
            "changed.bsky.social"
        )
    elif mode == "denied":
        environment.denied["jokes"] = [{"source_post_uri": JOKE}]
    elif mode == "missing_commit":
        environment.client.com.atproto.sync.get_latest_commit.return_value = {}
    with pytest.raises(ValueError):
        acknowledgements.publish_acknowledgement(environment.client, proposal)
    assert environment.client.com.atproto.repo.create_record.call_count == int(
        mode == "missing_after_write"
    )
    assert (
        bot_state.load_state()["starter_pack_acknowledgements"]["packs"][PACK]["status"]
        == "pending"
    )


def test_ledger_survives_domain_updates_and_roundtrip(environment):
    proposal = preview(environment)["proposals"][0]
    bot_state.update_state(
        lambda state: state["starter_pack_acknowledgements"]["packs"].update(
            {PACK: {"status": "pending", "proposal": proposal}}
        ),
        domains="social",
    )
    bot_state.update_state(
        lambda state: state["liked_replies"].update(last_checked_at=10),
        domains="social",
    )
    bot_state.update_state(
        lambda state: state["provider"].update(last_used="jokeapi"), domains="posting"
    )
    assert preview(environment)["proposals"] == [proposal]


def test_cli_default_is_read_only_and_writes_fixed_json_html(
    environment, monkeypatch, capsys
):
    monkeypatch.setattr(command, "OUTPUT_PATH", environment.root / "preview.json")
    monkeypatch.setattr(command, "PREVIEW_PATH", environment.root / "preview.html")
    monkeypatch.setattr(command, "DASHBOARD_DIR", environment.root)
    (environment.root / "data").mkdir()
    (environment.root / "data" / "metrics.json").write_text(
        json.dumps(environment.metrics)
    )
    monkeypatch.setattr(command, "login_client", lambda: (environment.client, "bot"))
    monkeypatch.setattr(sys, "argv", ["acknowledge"])
    before = bot_state.load_state()
    command.main()
    result = json.loads(capsys.readouterr().out)
    assert result["proposals"]
    assert bot_state.load_state() == before
    assert json.loads(command.OUTPUT_PATH.read_text()) == result
    rendered = command.PREVIEW_PATH.read_text()
    assert "not published" in rendered and "embed.bsky.app/embed/" in rendered
    assert f"embed.bsky.app/embed/{JOKE.removeprefix('at://')}" in rendered
    assert "embed.bsky.app/embed/at://" not in rendered
    environment.client.com.atproto.repo.create_record.assert_not_called()


def test_cli_publish_requires_explicit_matching_approval(environment, monkeypatch):
    monkeypatch.setattr(command, "login_client", lambda: (environment.client, "bot"))
    monkeypatch.setattr(sys, "argv", ["acknowledge", "--mode", "publish"])
    with pytest.raises(SystemExit):
        command.main()
    environment.client.com.atproto.repo.create_record.assert_not_called()


@pytest.mark.parametrize("mode", ["baseline", "publish", "wrong_pack", "invalid_uri"])
def test_cli_explicit_modes_and_approval(environment, monkeypatch, capsys, mode):
    monkeypatch.setattr(command, "login_client", lambda: (environment.client, "bot"))
    monkeypatch.setattr(command, "OUTPUT_PATH", environment.root / "preview.json")
    if mode == "baseline":
        bot_state.update_state(
            lambda state: state["starter_pack_acknowledgements"].update(
                baseline_at=None
            ),
            domains="social",
        )
        monkeypatch.setattr(sys, "argv", ["acknowledge", "--mode", "baseline"])
        command.main()
        assert json.loads(capsys.readouterr().out)["counts"]["member"] == 1
    else:
        proposal = preview(environment)["proposals"][0]
        command.OUTPUT_PATH.write_text(json.dumps({"proposals": [proposal]}))
        approved = PACK if mode == "publish" else PACK + "wrong"
        if mode == "invalid_uri":
            approved = "https://invalid.example/pack"
        monkeypatch.setattr(
            sys, "argv", ["acknowledge", "--mode", "publish", "--pack-uri", approved]
        )
        environment.client.com.atproto.repo.get_record.return_value = receipt(proposal)
        if mode == "publish":
            command.main()
            assert json.loads(capsys.readouterr().out)["pack_uri"] == PACK
        else:
            with pytest.raises(SystemExit):
                command.main()


def test_missing_post_array_is_not_a_successful_empty_result(environment):
    environment.client.app.bsky.feed.get_posts.return_value = {}
    with pytest.raises(ValueError, match="no post array"):
        preview(environment)


def test_receipt_accepts_sdk_models(environment):
    from atproto import models

    proposal = preview(environment)["proposals"][0]
    value = models.AppBskyFeedPost.Record.model_validate(proposal["record"])
    uri, cid = acknowledgements._verify_receipt(
        environment.client, SimpleNamespace(**receipt(proposal, value)), proposal
    )
    assert uri.endswith(proposal["rkey"]) and cid == CID


def test_invalid_pack_and_uninitialised_baseline_cannot_publish(environment):
    proposal = preview(environment)["proposals"][0]
    with pytest.raises(ValueError, match="Invalid acknowledgement"):
        acknowledgements.publish_acknowledgement(
            environment.client, {**proposal, "pack_uri": "invalid"}
        )
    bot_state.update_state(
        lambda state: state["starter_pack_acknowledgements"].update(baseline_at=None),
        domains="social",
    )
    with pytest.raises(ValueError, match="initialised baseline"):
        acknowledgements.publish_acknowledgement(environment.client, proposal)
    environment.client.com.atproto.repo.create_record.assert_not_called()


def test_global_dry_run_blocks_baseline_and_publish_without_state_changes(
    environment, monkeypatch
):
    proposal = preview(environment)["proposals"][0]
    before = bot_state.load_state()
    monkeypatch.setenv("BLUESKY_DRY_RUN", "true")
    with pytest.raises(ValueError, match="Dry-run mode"):
        acknowledgements.baseline_memberships(environment.client)
    with pytest.raises(ValueError, match="Dry-run mode"):
        acknowledgements.publish_acknowledgement(environment.client, proposal)
    assert bot_state.load_state() == before
    environment.client.com.atproto.repo.create_record.assert_not_called()


def test_own_pack_cannot_publish_even_with_altered_preview(environment):
    own_pack = PACK.replace(CREATOR, BOT)
    environment.client.app.bsky.graph.get_starter_pack.return_value[
        "starterPack"
    ].update(uri=own_pack, creator={"did": BOT})
    environment.client.app.bsky.actor.get_profile.return_value["did"] = BOT
    proposal = acknowledgements._proposal(
        environment.client, own_pack, {"uri": JOKE, "cid": CID}
    )
    with pytest.raises(ValueError, match="own starter pack"):
        acknowledgements._revalidate_intent(environment.client, proposal)


def test_workflow_is_manual_baseline_preview_only_and_serialises_state_writes():
    from thejokebot.paths import PROJECT_ROOT

    workflow = (
        PROJECT_ROOT / ".github/workflows/bluesky_acknowledge_starter_packs.yml"
    ).read_text()
    assert "schedule:" not in workflow and "workflow_dispatch:" in workflow
    assert "group: joke_and_social_state_writer" in workflow
    assert '--mode "$MODE"' in workflow
    assert "baseline|preview)" in workflow
    assert "          - publish" not in workflow
    assert "state/social_state.json" in workflow
    assert "steps.acknowledgement.outcome == 'success'" in workflow
