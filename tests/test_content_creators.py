"""Outgoing manual and automated interactions protect and follow their creators."""

import copy
from types import SimpleNamespace
from unittest import mock

import pytest
import requests
from atproto import models
from atproto_client.exceptions import AtProtocolError, BadRequestError
from atproto_client.request import Response

from thejokebot import config, content_creators, follow_records, state
from thejokebot.state_transactions import CheckpointError
from thejokebot.commands import (
    dashboard_workflows,
    follow_interactors,
    follows_and_likes,
    interaction_likes,
    unfollow,
)

BOT = "did:plc:bot"
LIKE = "app.bsky.feed.like"
REPOST = "app.bsky.feed.repost"


def interaction(
    did, collection=LIKE, key="key", subject_collection="app.bsky.feed.post"
):
    return {
        "uri": f"at://{BOT}/{collection}/{key}",
        "value": {
            "$type": collection,
            "createdAt": "2026-11-13T00:00:00Z",
            "subject": {
                "uri": f"at://{did}/{subject_collection}/post",
                "cid": "post-cid",
            },
        },
    }


@pytest.fixture
def account(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "STATE_FILE", str(tmp_path / "bot_state.json"))
    state.save_state(state._default_state(), domains="social")
    for module in (
        content_creators,
        follow_interactors,
        interaction_likes,
        follow_records,
    ):
        monkeypatch.setattr(module, "retry_network_call", lambda fn, description: fn())
    client = mock.Mock()
    client.me.did = BOT
    client.com.atproto.repo.list_records.return_value = {"records": []}
    client.get_follows.return_value = SimpleNamespace(follows=[], cursor=None)
    client.get_profiles.side_effect = lambda actors: {
        "profiles": [{"did": did, "viewer": {}} for did in actors]
    }
    return client, tmp_path / "state" / "social_state.json"


def test_complete_scan_backfills_manual_records_and_retains_protection(account):
    client, social_file = account
    typed = models.AppBskyFeedLike.Record.model_validate(
        interaction("did:plc:typed")["value"]
    )
    typed_record = SimpleNamespace(uri=f"at://{BOT}/{LIKE}/typed", value=typed)
    client.com.atproto.repo.list_records.side_effect = [
        {"records": [interaction("did:plc:liked"), typed_record], "cursor": "next"},
        {"records": [interaction(BOT), interaction("did:plc:liked", key="again")]},
        {"records": [interaction("did:plc:shared", REPOST)]},
    ]
    working = state.load_state()
    expected = {"did:plc:liked", "did:plc:typed", "did:plc:shared"}
    assert content_creators.sync_protections(client, working, False) == expected
    calls = client.com.atproto.repo.list_records.call_args_list
    assert calls[1].args[0]["cursor"] == "next"
    assert [call.args[0]["collection"] for call in calls] == [LIKE, LIKE, REPOST]
    assert content_creators.get_protected_dids(state.load_state()) == expected

    client.com.atproto.repo.list_records.side_effect = None
    client.com.atproto.repo.list_records.return_value = {"records": []}
    assert content_creators.sync_protections(client, working, False) == expected
    assert social_file.exists()


@pytest.mark.parametrize("failure", ["network", "cursor", "limit", "malformed"])
def test_incomplete_scan_never_checkpoints_partial_protections(
    account, monkeypatch, failure
):
    client, social_file = account
    before = social_file.read_bytes()
    first = {"records": [interaction("did:plc:first")]}
    responses = [first, requests.Timeout("unavailable")]
    expected_error = requests.Timeout
    if failure == "cursor":
        responses = [{**first, "cursor": "same"}, {"records": [], "cursor": "same"}]
        expected_error = content_creators.IncompletePaginationError
    elif failure == "limit":
        monkeypatch.setattr(content_creators, "_MAX_PAGES", 1)
        responses = [{**first, "cursor": "more"}]
        expected_error = content_creators.IncompletePaginationError
    elif failure == "malformed":
        responses = [first, {"records": None}]
        expected_error = content_creators.IncompletePaginationError
    client.com.atproto.repo.list_records.side_effect = responses
    with pytest.raises(expected_error):
        content_creators.sync_protections(client, state.load_state(), False)
    assert social_file.read_bytes() == before


def test_runtime_limit_covers_retries_and_returning_requests(account, monkeypatch):
    client, social_file = account
    before = social_file.read_bytes()
    monkeypatch.setattr(
        content_creators.time, "monotonic", mock.Mock(side_effect=[0, 0, 121])
    )
    with pytest.raises(content_creators.IncompletePaginationError, match="runtime"):
        content_creators.sync_protections(client, state.load_state(), False)
    assert client.com.atproto.repo.list_records.call_count == 1
    assert social_file.read_bytes() == before

    client.com.atproto.repo.list_records.reset_mock()
    monkeypatch.setattr(
        content_creators.time, "monotonic", mock.Mock(side_effect=[0, 121])
    )
    with pytest.raises(content_creators.IncompletePaginationError, match="runtime"):
        content_creators.sync_protections(client, state.load_state(), False)
    client.com.atproto.repo.list_records.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"uri": f"at://did:plc:other/{LIKE}/key"},
        {"uri": f"at://{BOT}/{LIKE}/key/extra"},
        {"value": {"$type": REPOST}},
        {"value": {"$type": LIKE, "subject": {"uri": "https://example.com"}}},
    ],
)
def test_mismatched_records_fail_closed(account, change):
    client, social_file = account
    before = social_file.read_bytes()
    client.com.atproto.repo.list_records.return_value = {
        "records": [interaction("did:plc:author") | change]
    }
    with pytest.raises(ValueError):
        content_creators.sync_protections(client, state.load_state(), False)
    assert social_file.read_bytes() == before


def test_mixed_post_and_custom_feed_likes_complete_without_following_feed_creators(
    account, capsys
):
    client, _ = account
    feed_like = interaction(
        "did:plc:feed", key="feed", subject_collection="app.bsky.feed.generator"
    )
    typed_feed_like = SimpleNamespace(
        uri=feed_like["uri"],
        value=models.AppBskyFeedLike.Record.model_validate(feed_like["value"]),
    )
    client.com.atproto.repo.list_records.side_effect = [
        {
            "records": [
                interaction("did:plc:post"),
                feed_like,
                typed_feed_like,
                interaction("did:plc:reposter", subject_collection=REPOST),
            ]
        },
        {"records": [interaction("did:plc:shared", REPOST)]},
    ]
    expected = {"did:plc:post", "did:plc:reposter", "did:plc:shared"}
    assert (
        content_creators.sync_protections(client, state.load_state(), False) == expected
    )
    assert content_creators.get_protected_dids(state.load_state()) == expected
    assert "custom-feed" in capsys.readouterr().out


def test_malformed_custom_feed_subject_still_fails_closed(account):
    client, social_file = account
    before = social_file.read_bytes()
    malformed = interaction("did:plc:feed")
    malformed["value"]["subject"]["uri"] = "at://did:plc:feed/app.bsky.feed.generator"
    client.com.atproto.repo.list_records.return_value = {"records": [malformed]}
    with pytest.raises(ValueError, match="subject URI"):
        content_creators.sync_protections(client, state.load_state(), False)
    assert social_file.read_bytes() == before


@pytest.mark.parametrize("cursor", [1, "   "])
def test_invalid_cursors_cannot_authorise_unfollows(account, cursor):
    client, _ = account
    client.com.atproto.repo.list_records.return_value = {
        "records": [],
        "cursor": cursor,
    }
    with pytest.raises(content_creators.IncompletePaginationError, match="cursor"):
        content_creators.sync_protections(client, state.load_state(), False)


def test_checkpoint_merges_concurrent_protection_without_overwriting_other_data(
    account,
):
    client, _ = account
    stale = state.load_state()
    state.update_state(
        lambda latest: latest["follow_tracking"].update(
            content_creator_dids=["did:plc:concurrent"],
            following_snapshot_dids=["other"],
        ),
        domains="social",
    )
    client.com.atproto.repo.list_records.side_effect = [
        {"records": [interaction("did:plc:new")]},
        {"records": []},
    ]
    content_creators.sync_protections(client, stale, False)
    saved = state.load_state()
    assert content_creators.get_protected_dids(saved) == {
        "did:plc:concurrent",
        "did:plc:new",
    }
    assert state.get_following_snapshot_dids(saved) == {"other"}


def test_malformed_persisted_protection_is_not_silently_discarded(account):
    client, _ = account
    broken = state.load_state()
    broken["follow_tracking"]["content_creator_dids"] = ["not-a-did"]
    with pytest.raises(ValueError, match="protections"):
        content_creators.sync_protections(client, broken, False)
    client.com.atproto.repo.list_records.assert_not_called()


def test_creator_follows_obey_ten_action_cap_and_existing_summary_contract(
    account, monkeypatch
):
    client, _ = account
    authors = {f"did:plc:author{i:02}" for i in range(13)}
    client.com.atproto.repo.list_records.side_effect = [
        {
            "records": [
                interaction(did, key=str(i)) for i, did in enumerate(sorted(authors))
            ]
        },
        {"records": []},
    ]
    follow = mock.Mock(return_value=True)
    monkeypatch.setattr(follow_interactors, "follow_account", follow)
    summary = {
        "interaction_candidates": 2,
        "interaction_eligible": 2,
        "interaction_added": 2,
    }
    working = state.load_state()
    assert (
        follow_interactors.follow_content_creators(client, working, False, 0, summary)
        == 10
    )
    assert [call.args[2] for call in follow.call_args_list] == sorted(authors)[:10]
    assert content_creators.get_protected_dids(state.load_state()) == authors
    parsed = dashboard_workflows._workflow_activity_counts(
        "bluesky_follows_and_likes",
        follows_and_likes._social_summary_line(summary, False),
    )
    assert parsed is not None
    assert parsed["follows"] == parsed["interaction_added"] == 12
    assert parsed["interaction_eligible"] == 12
    assert parsed["interaction_candidates"] == 15
    assert "did:" not in str(parsed)
    client.get_follows.return_value = SimpleNamespace(
        follows=[SimpleNamespace(did=did) for did in sorted(authors)[:10]],
        cursor=None,
    )
    client.com.atproto.repo.list_records.side_effect = None
    client.com.atproto.repo.list_records.return_value = {"records": []}
    assert (
        follow_interactors.follow_content_creators(client, working, False, 0, {}) == 3
    )


def test_follow_filter_respects_existing_follows_blocks_and_explicit_exclusions(
    account, monkeypatch
):
    client, _ = account
    authors = {
        "existing",
        "blocked",
        "muted",
        "reverseblock",
        "manual",
        "auto",
        "missing",
        "lag",
    }
    working = state.load_state()
    working["follow_tracking"]["content_creator_dids"] = [
        f"did:plc:{name}" for name in sorted(authors)
    ]
    state.record_unfollow(working, "did:plc:manual", reason="manual_block")
    state.record_unfollow(working, "did:plc:auto")
    client.get_follows.return_value = SimpleNamespace(
        follows=[SimpleNamespace(did="did:plc:existing")], cursor=None
    )
    client.get_profiles.return_value = {
        "profiles": [
            {"did": "did:plc:blocked", "viewer": {"blocking": "at://block/key"}},
            {"did": "did:plc:muted", "viewer": {"muted": True}},
            {"did": "did:plc:reverseblock", "viewer": {"blockedBy": True}},
            {"did": "did:plc:lag", "viewer": {"following": "at://follow/key"}},
            {"did": "did:plc:auto", "viewer": {}},
        ]
    }
    client.get_profiles.side_effect = None
    follow = mock.Mock(return_value=True)
    monkeypatch.setattr(follow_interactors, "follow_account", follow)
    assert (
        follow_interactors.follow_content_creators(client, working, False, 0, {}) == 1
    )
    assert follow.call_args.args[2] == "did:plc:auto"
    assert set(client.get_profiles.call_args.args[0]) == {
        f"did:plc:{name}" for name in authors - {"existing", "manual"}
    }


@pytest.mark.parametrize("response_format", ["sdk", "json"])
def test_list_blocked_creators_are_never_followed(
    account, monkeypatch, response_format
):
    client, _ = account
    did = "did:plc:blocked"
    block_list = {
        "cid": "list-cid",
        "name": "Blocked creators",
        "purpose": "app.bsky.graph.defs#modlist",
        "uri": "at://did:plc:owner/app.bsky.graph.list/list",
    }
    if response_format == "sdk":
        profile = models.AppBskyActorDefs.ProfileViewDetailed(
            did=did,
            handle="creator.example",
            viewer=models.AppBskyActorDefs.ViewerState(
                blocking_by_list=models.AppBskyGraphDefs.ListViewBasic.model_validate(
                    block_list
                )
            ),
        )
    else:
        profile = {"did": did, "viewer": {"blockingByList": block_list}}
    client.get_profiles.side_effect = None
    client.get_profiles.return_value = {"profiles": [profile]}
    client.com.atproto.repo.list_records.side_effect = [
        {"records": [interaction(did)]},
        {"records": []},
    ]
    follow = mock.Mock(return_value=True)
    monkeypatch.setattr(follow_interactors, "follow_account", follow)
    assert (
        follow_interactors.follow_content_creators(
            client, state.load_state(), False, 0, {}
        )
        == 0
    )
    client.app.bsky.graph.follow.create.assert_not_called()
    follow.assert_not_called()
    assert state.load_state()["follow_tracking"]["pending_follows"] == {}


def test_recent_incoming_follow_is_not_recreated_when_both_graph_reads_lag(account):
    client, _ = account
    did = "did:plc:recent"
    working = state.load_state()
    follow_interactors._checkpoint_follow(working, did)
    intent = follow_records._build_intent(BOT, did, "interaction")
    intent["record"]["createdAt"] = "2026-11-12T00:00:00Z"
    client.com.atproto.repo.get_record.return_value = {
        "uri": intent["uri"],
        "cid": "follow-cid",
        "value": intent["record"],
    }
    client.com.atproto.repo.list_records.side_effect = [
        {"records": [interaction(did)]},
        {"records": []},
    ]
    assert (
        follow_interactors.follow_content_creators(client, working, False, 0, {}) == 0
    )
    client.get_profiles.assert_not_called()
    client.com.atproto.repo.get_record.assert_not_called()
    client.app.bsky.graph.follow.create.assert_not_called()
    assert state.load_state()["follow_tracking"]["pending_follows"] == {}


@pytest.mark.parametrize(
    "error", [ValueError("receipt mismatch"), AtProtocolError("rejected")]
)
def test_partial_creator_success_reaches_failed_run_dashboard_totals(
    account, monkeypatch, capsys, error
):
    client, _ = account
    client.com.atproto.repo.list_records.side_effect = [
        {"records": [interaction(f"did:plc:author{i}", key=str(i)) for i in range(3)]},
        {"records": []},
    ]
    monkeypatch.setattr(follows_and_likes, "login_client", lambda: (client, "bot"))
    monkeypatch.setattr(
        follows_and_likes,
        "get_runtime_controls",
        lambda: {"dry_run": False, "action_delay_seconds": 0},
    )
    monkeypatch.setattr(
        follows_and_likes.blocks,
        "reconcile_configured_blocks",
        mock.Mock(return_value=0),
    )

    def follow_back(_client, _dry_run, _delay, summary, _state):
        summary["follow_back_added"] = 2

    monkeypatch.setattr(follows_and_likes, "follow_back", follow_back)
    for phase in (
        "follow_interactors",
        "track_starter_pack_follows",
        "reply_to_joke_requests",
        "like_replies",
    ):
        monkeypatch.setattr(follows_and_likes, phase, mock.Mock(return_value=0))
    follow = mock.Mock(side_effect=[True, error])
    monkeypatch.setattr(follow_interactors, "follow_account", follow)
    with pytest.raises(RuntimeError, match="1 failed action"):
        follows_and_likes.main()
    counts = dashboard_workflows._workflow_activity_counts(
        "bluesky_follows_and_likes", capsys.readouterr().out
    )
    assert counts is not None
    assert counts["interaction_added"] == 1
    assert counts["follows"] == 3
    assert counts["failed"] == 1
    assert follow.call_count == 2


def test_partial_success_does_not_swallow_checkpoint_failure(account, monkeypatch):
    client, _ = account
    client.com.atproto.repo.list_records.side_effect = [
        {"records": [interaction(f"did:plc:author{i}", key=str(i)) for i in range(3)]},
        {"records": []},
    ]
    follow = mock.Mock(side_effect=[True, CheckpointError("disk unavailable")])
    monkeypatch.setattr(follow_interactors, "follow_account", follow)
    summary = {"interaction_added": 2}
    with pytest.raises(CheckpointError, match="disk unavailable"):
        follow_interactors.follow_content_creators(
            client, state.load_state(), False, 0, summary
        )
    assert summary["interaction_added"] == 3
    assert follow.call_count == 2


@pytest.mark.parametrize("profiles", [None, [{"did": "did:plc:wrong"}]])
def test_bad_profiles_prevent_all_creator_follow_actions(
    account, monkeypatch, profiles
):
    client, _ = account
    working = state.load_state()
    working["follow_tracking"]["content_creator_dids"] = ["did:plc:author"]
    client.get_profiles.side_effect = None
    client.get_profiles.return_value = {"profiles": profiles}
    follow = mock.Mock()
    monkeypatch.setattr(follow_interactors, "follow_account", follow)
    with pytest.raises(ValueError):
        follow_interactors.follow_content_creators(client, working, False, 0, {})
    follow.assert_not_called()


def test_dry_run_changes_neither_disk_nor_account(account):
    client, social_file = account
    before = social_file.read_bytes()
    client.com.atproto.repo.list_records.side_effect = [
        {"records": [interaction("did:plc:author")]},
        {"records": []},
    ]
    assert (
        follow_interactors.follow_content_creators(
            client, state.load_state(), True, 0, {}
        )
        == 1
    )
    assert social_file.read_bytes() == before
    client.app.bsky.graph.follow.create.assert_not_called()


def test_automated_like_is_discovered_and_followed_with_exact_receipt(account):
    client, _ = account
    liked_uri = "at://did:plc:author/app.bsky.feed.post/post"
    records = {}

    def get_record(params):
        result = records.get((params["collection"], params["rkey"]))
        if result is None:
            raise BadRequestError(Response(False, 400, {"error": "RecordNotFound"}, {}))
        return result

    def create_record(*, repo, record, rkey):
        value = record.model_dump(by_alias=True, exclude_none=True)
        collection = value["$type"]
        receipt = {
            "uri": f"at://{repo}/{collection}/{rkey}",
            "cid": "receipt-cid",
            "value": value,
        }
        records[(collection, rkey)] = receipt
        return SimpleNamespace(**receipt)

    client.com.atproto.repo.get_record.side_effect = get_record
    client.app.bsky.feed.like.create.side_effect = create_record
    client.app.bsky.graph.follow.create.side_effect = create_record
    client.com.atproto.repo.list_records.side_effect = lambda params: {
        "records": [
            value
            for (collection, _), value in records.items()
            if collection == params["collection"]
        ]
    }
    interaction_likes._create_or_reconcile_like(client, liked_uri, "post-cid")
    working = state.load_state()
    assert (
        follow_interactors.follow_content_creators(client, working, False, 0, {}) == 1
    )
    assert content_creators.get_protected_dids(state.load_state()) == {"did:plc:author"}
    assert state.get_follow_grace_dids(state.load_state()) == {"did:plc:author"}
    client.get_follows.return_value = SimpleNamespace(
        follows=[SimpleNamespace(did="did:plc:author")], cursor=None
    )
    assert (
        follow_interactors.follow_content_creators(client, working, False, 0, {}) == 0
    )
    assert client.app.bsky.graph.follow.create.call_count == 1


def test_unfollow_excludes_permanent_creator_after_grace_expires(account):
    _, _ = account
    following = {"did:plc:creator": "uri1", "did:plc:other": "uri2"}
    working = state.load_state()
    working["follow_tracking"]["content_creator_dids"] = ["did:plc:creator"]
    state.set_following_snapshot_dids(working, set(following))
    state.record_follow_grace(working, "did:plc:creator")
    working["follow_grace"]["entries"][0]["followed_at"] = 0
    state.save_state(working, domains="social")
    _, all_candidates, selected = unfollow._prepare_unfollow_candidates(
        following, set(), set(), 10
    )
    assert all_candidates == selected == ["did:plc:other"]


@pytest.mark.parametrize("dry_run", [True, False])
def test_unfollow_reads_manual_interactions_before_selecting_candidates(
    account, monkeypatch, dry_run
):
    client, social_file = account
    working = state.load_state()
    state.set_following_snapshot_dids(working, {"did:plc:creator", "did:plc:other"})
    state.save_state(working, domains="social")
    before = social_file.read_bytes()
    client.com.atproto.repo.list_records.side_effect = [
        {"records": []},
        {"records": [interaction("did:plc:creator", REPOST)]},
    ]
    monkeypatch.setattr(unfollow, "login_client", lambda: (client, "bot"))
    monkeypatch.setattr(
        unfollow,
        "get_runtime_controls",
        lambda: {"dry_run": dry_run, "action_delay_seconds": 0},
    )
    monkeypatch.setattr(unfollow, "_resolve_ignorable_dids", lambda *args: set())
    monkeypatch.setattr(unfollow, "_load_source_list_uri", lambda: "")
    graph = mock.Mock(
        side_effect=[
            [],
            [
                SimpleNamespace(did=did, viewer=SimpleNamespace(following="uri"))
                for did in ("did:plc:creator", "did:plc:other")
            ],
        ]
    )
    monkeypatch.setattr(unfollow, "fetch_paginated_data", graph)
    execute = mock.Mock(return_value=(0, 0, 0, False))
    monkeypatch.setattr(unfollow, "_execute_unfollow_loop", execute)
    assert unfollow.main() == 0
    assert execute.call_args.args[2] == ["did:plc:other"]
    if dry_run:
        assert social_file.read_bytes() == before


def test_unfollow_fails_before_reconciliation_when_interactions_are_unreadable(
    account, monkeypatch
):
    client, social_file = account
    before = social_file.read_bytes()
    client.com.atproto.repo.list_records.side_effect = requests.Timeout("unavailable")
    monkeypatch.setattr(unfollow, "login_client", lambda: (client, "bot"))
    monkeypatch.setattr(
        unfollow,
        "get_runtime_controls",
        lambda: {"dry_run": False, "action_delay_seconds": 0},
    )
    monkeypatch.setattr(unfollow, "_resolve_ignorable_dids", lambda *args: set())
    monkeypatch.setattr(unfollow, "_load_source_list_uri", lambda: "")
    monkeypatch.setattr(unfollow, "fetch_paginated_data", lambda *args, **kwargs: [])
    prepare = mock.Mock()
    monkeypatch.setattr(unfollow, "_prepare_unfollow_candidates", prepare)
    assert unfollow.main() == 1
    prepare.assert_not_called()
    client.unfollow.assert_not_called()
    assert social_file.read_bytes() == before


def test_creator_limit_cannot_be_zero_or_unbounded():
    payload = copy.deepcopy(config._DEFAULT_CONFIG)
    payload["follows_and_likes"]["content_follow_max_actions"] = 0
    with pytest.raises(ValueError, match="content_follow_max_actions"):
        config._validate_config(payload)
