"""Exercise social checkpoints with real state files and stale working snapshots."""

import copy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

import pytest
import requests
from atproto import models
from atproto_client.exceptions import BadRequestError
from atproto_client.request import Response

from thejokebot import follow_records, state_transactions, state
from thejokebot.commands import follow_back, follow_interactors, interaction_likes
from thejokebot.commands import joke_requests, starter_pack_attribution


@pytest.fixture
def social_file(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "STATE_FILE", str(tmp_path / "bot_state.json"))
    state.save_state(state._default_state(), domains=("posting", "social"))
    for module in (interaction_likes, follow_records):
        monkeypatch.setattr(module, "retry_network_call", lambda fn, description: fn())
    return tmp_path / "state" / "social_state.json"


def test_like_checkpoint_merges_newer_receipts_and_unrelated_fields(social_file):
    stale = state.load_state()

    def other_work(latest):
        state.record_liked_reply_uri(latest, "other-like")
        state.record_replied_joke_request_uri(latest, "other-request")
        latest["follow_fellows"]["feed_offset"] = 10

    state.update_state(other_work, domains="social")
    interaction_likes._checkpoint_likes(stale, {"our-like"})
    latest = state.load_state()
    assert state.get_liked_reply_uris(latest) == {"our-like", "other-like"}
    assert state.get_replied_joke_request_uris(latest) == {"other-request"}
    assert latest["follow_fellows"]["feed_offset"] == 10


def test_reply_receipts_update_both_domains_without_replacing_them(social_file):
    stale = state.load_state()

    def other_work(latest):
        state.advance_posting_tag_offset(latest, 2, 10)
        state.record_liked_reply_uri(latest, "other-like")

    state.update_state(other_work, domains=("posting", "social"))
    joke_requests._checkpoint_reply(stale, "request", pool_size=10)
    latest = state.load_state()
    assert state.get_posting_tag_offset(latest) == 3
    assert state.get_replied_joke_request_uris(latest) == {"request"}
    assert state.get_liked_reply_uris(latest) == {"other-like"}
    joke_requests._checkpoint_reply(state._default_state(), "request", pool_size=10)
    assert state.get_posting_tag_offset(state.load_state()) == 3


@pytest.mark.parametrize(
    "upper,expected,boundary",
    [(90, 100, {"existing"}), (100, 100, {"existing", "ours"}), (110, 110, {"ours"})],
)
def test_request_checkpoints_never_regress(social_file, upper, expected, boundary):
    stale = state.load_state()
    state.update_state(
        lambda latest: state.set_joke_request_checkpoint(latest, 100, {"existing"}),
        domains="social",
    )
    joke_requests._checkpoint_scan(stale, upper, {"ours"})
    assert state.get_joke_request_checkpoint(state.load_state()) == (expected, boundary)


def test_likes_survive_later_page_failure_and_duplicate_run(social_file):
    client = mock.Mock()
    notification = {
        "reason": "reply",
        "uri": "our-like",
        "cid": "cid",
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "record": {"text": "hello"},
    }
    page = SimpleNamespace(notifications=[notification], cursor="next")
    client.app.bsky.notification.list_notifications.side_effect = [
        page,
        requests.RequestException("offline"),
    ]
    client.like.side_effect = lambda **kwargs: state.update_state(
        lambda latest: latest["follow_fellows"].update(feed_offset=10), domains="social"
    )
    assert interaction_likes.like_replies(client, state.load_state(), False, 0) == 1
    assert state.get_liked_reply_uris(state.load_state()) == {"our-like"}
    assert state.get_likes_last_checked_at(state.load_state()) is None
    assert state.load_state()["follow_fellows"]["feed_offset"] == 10
    client.app.bsky.notification.list_notifications.side_effect = [
        SimpleNamespace(notifications=[notification], cursor=None)
    ]
    assert interaction_likes.like_replies(client, state.load_state(), False, 0) == 0
    client.like.assert_called_once()
    assert state.get_likes_last_checked_at(state.load_state()) is not None


def test_failed_transaction_does_not_mutate_working_state(social_file):
    working = state.load_state()
    before = copy.deepcopy(working)
    social_file.write_text("{broken", encoding="utf-8")
    with pytest.raises(state.StateReadError):
        state_transactions.apply(
            working, lambda latest: state.record_liked_reply_uri(latest, "new")
        )
    assert working == before
    assert social_file.read_text(encoding="utf-8") == "{broken"


def test_checkpoint_validation_error_cannot_be_swallowed_as_api_error(social_file):
    working = state.load_state()
    before = copy.deepcopy(working)
    with mock.patch.object(
        state, "update_state", side_effect=ValueError("invalid state")
    ):
        with pytest.raises(state_transactions.CheckpointError):
            state_transactions.apply(
                working, lambda latest: state.record_liked_reply_uri(latest, "new")
            )
    assert working == before


def test_follow_receipts_preserve_newer_social_fields(social_file):
    stale = state.load_state()
    client = mock.Mock()
    client.me.did = "did:plc:bot"

    def missing_record(params):
        raise BadRequestError(Response(False, 400, {"error": "RecordNotFound"}, {}))

    def create_record(*, repo, record, rkey):
        return SimpleNamespace(
            uri=f"at://{repo}/app.bsky.graph.follow/{rkey}", cid="follow-cid"
        )

    client.com.atproto.repo.get_record.side_effect = missing_record
    client.app.bsky.graph.follow.create.side_effect = create_record
    state.update_state(
        lambda latest: state.record_liked_reply_uri(latest, "other-like"),
        domains="social",
    )
    follow_interactors._checkpoint_follow(stale, "interactor")
    follow_back._follow_candidates(
        client,
        stale,
        ["follower"],
        False,
        0,
        set(),
        {"follow_back_added": 0, "failed": 0},
    )
    latest = state.load_state()
    assert "interactor" in state.get_follow_grace_dids(latest)
    assert len(state.get_acquisition_cohorts(latest)["members"]) == 2
    assert state.get_liked_reply_uris(latest) == {"other-like"}


def test_follow_rkey_is_a_deterministic_tid():
    first = follow_records._follow_rkey("did:plc:subject")
    assert first == follow_records._follow_rkey("did:plc:subject")
    assert first != follow_records._follow_rkey("did:plc:other")
    assert len(first) == 13
    assert first[0] in "234567abcdefghij"
    assert set(first) <= set("234567abcdefghijklmnopqrstuvwxyz")


def test_pending_follow_intent_must_be_well_formed(social_file):
    latest = state._default_state()
    latest["follow_tracking"]["pending_follows"]["did:plc:subject"] = "invalid"

    with pytest.raises(ValueError, match="Invalid pending follow intent"):
        follow_records._prepare_intent(
            latest, "did:plc:bot", "did:plc:subject", "followback"
        )


def test_follow_receipt_validation_rejects_malformed_values(social_file):
    valid_record = models.AppBskyGraphFollow.Record(
        subject="did:plc:subject",
        created_at="2026-11-09T00:00:00Z",
    )
    assert follow_records._normalise_follow_record(valid_record)["subject"] == (
        "did:plc:subject"
    )

    with pytest.raises(ValueError, match="unexpected value"):
        follow_records._normalise_follow_record(None)
    with pytest.raises(ValueError, match="malformed"):
        follow_records._normalise_follow_record(
            {
                "$type": "app.bsky.graph.follow",
                "createdAt": "2026-11-09T00:00:00Z",
            }
        )

    intent = follow_records._build_intent(
        "did:plc:bot", "did:plc:subject", "followback"
    )
    response = {
        "uri": intent["uri"],
        "cid": "follow-cid",
        "value": {
            "$type": "app.bsky.graph.follow",
            "subject": "did:plc:other",
            "createdAt": intent["record"]["createdAt"],
        },
    }
    with pytest.raises(ValueError, match="does not match"):
        follow_records._verify_record_response(response, intent)
    with pytest.raises(ValueError, match="has no value"):
        follow_records._verify_existing_record(
            {"uri": intent["uri"], "cid": "follow-cid"}, intent
        )


def test_non_missing_bad_request_during_follow_read_is_not_swallowed(social_file):
    client = mock.Mock()
    client.com.atproto.repo.get_record.side_effect = BadRequestError(
        Response(False, 400, {"error": "InvalidRequest"}, {})
    )
    intent = follow_records._build_intent(
        "did:plc:bot", "did:plc:subject", "followback"
    )

    with pytest.raises(BadRequestError):
        follow_records._record_at_key(client, "did:plc:bot", intent)


def test_unknown_follow_source_is_rejected_before_state_access(social_file):
    client = mock.Mock()
    client.me.did = "did:plc:bot"

    with mock.patch.object(state, "load_state") as load_state:
        with pytest.raises(ValueError, match="Unknown follow source"):
            follow_records.follow_account(client, None, "did:plc:subject", "unknown")

    load_state.assert_not_called()


def test_checkpoint_ignores_absent_intent_and_rejects_changed_intent(social_file):
    did = "did:plc:subject"
    intent = follow_records._build_intent("did:plc:bot", did, "starter_pack")
    follow_records._checkpoint_follow(state._default_state(), did, intent)

    changed = dict(intent, source="followback")

    def apply_changed_intent(working, operation, *, domains):
        working["follow_tracking"]["pending_follows"][did] = changed
        operation(working)

    with mock.patch.object(
        follow_records.state_transactions, "apply", side_effect=apply_changed_intent
    ):
        with pytest.raises(ValueError, match="changed during reconciliation"):
            follow_records._checkpoint_follow(state._default_state(), did, intent)


def test_existing_pending_follow_is_verified_without_another_create(social_file):
    did = "did:plc:subject"
    intent = follow_records._build_intent("did:plc:bot", did, "discovery")
    state.update_state(
        lambda latest: latest["follow_tracking"]["pending_follows"].update(
            {did: intent}
        ),
        domains="social",
    )
    working = state.load_state()
    client = mock.Mock()
    client.me.did = "did:plc:bot"
    client.com.atproto.repo.get_record.return_value = SimpleNamespace(
        uri=intent["uri"], cid="follow-cid", value=intent["record"]
    )

    assert follow_records.follow_account(client, working, did, "discovery")

    latest = state.load_state()
    assert not latest["follow_tracking"]["pending_follows"]
    assert state.get_follow_grace_dids(latest, cutoff_ts=0) == {did}
    client.app.bsky.graph.follow.create.assert_not_called()


def test_uncertain_follow_write_preserves_intent_and_original_error(social_file):
    client = mock.Mock()
    client.me.did = "did:plc:bot"
    missing = BadRequestError(Response(False, 400, {"error": "RecordNotFound"}, {}))
    client.com.atproto.repo.get_record.side_effect = [
        missing,
        requests.Timeout("read lost"),
    ]
    client.app.bsky.graph.follow.create.side_effect = requests.Timeout("write lost")

    with pytest.raises(requests.Timeout, match="write lost"):
        follow_records.follow_account(
            client, state.load_state(), "did:plc:subject", "followback"
        )

    assert set(state.load_state()["follow_tracking"]["pending_follows"]) == {
        "did:plc:subject"
    }
    client.app.bsky.graph.follow.create.assert_called_once()


def test_missing_record_after_failed_follow_write_does_not_retry(social_file):
    client = mock.Mock()
    client.me.did = "did:plc:bot"
    missing = BadRequestError(Response(False, 400, {"error": "RecordNotFound"}, {}))
    client.com.atproto.repo.get_record.side_effect = [missing, missing]
    client.app.bsky.graph.follow.create.side_effect = requests.Timeout("write lost")

    with pytest.raises(requests.Timeout, match="write lost"):
        follow_records.follow_account(
            client, state.load_state(), "did:plc:subject", "followback"
        )

    assert set(state.load_state()["follow_tracking"]["pending_follows"]) == {
        "did:plc:subject"
    }
    client.app.bsky.graph.follow.create.assert_called_once()


def test_reconciliation_keeps_pending_intent_when_record_is_absent(social_file):
    did = "did:plc:subject"
    intent = follow_records._build_intent("did:plc:bot", did, "followback")
    state.update_state(
        lambda latest: latest["follow_tracking"]["pending_follows"].update(
            {did: intent}
        ),
        domains="social",
    )
    client = mock.Mock()
    client.me.did = "did:plc:bot"
    client.com.atproto.repo.get_record.side_effect = BadRequestError(
        Response(False, 400, {"error": "RecordNotFound"}, {})
    )

    follow_records.reconcile_pending_follows(client, state.load_state())

    assert set(state.load_state()["follow_tracking"]["pending_follows"]) == {did}
    client.app.bsky.graph.follow.create.assert_not_called()


def test_accepted_follow_timeout_does_not_create_twice(social_file):
    client = mock.Mock()
    client.me.did = "did:plc:bot"
    accepted = {}
    created_rkeys = []

    def get_record(params):
        record = accepted.get(params["rkey"])
        if record is None:
            raise BadRequestError(Response(False, 400, {"error": "RecordNotFound"}, {}))
        return record

    def create_record(*, repo, record, rkey):
        created_rkeys.append(rkey)
        accepted[rkey] = SimpleNamespace(
            uri=f"at://{repo}/app.bsky.graph.follow/{rkey}",
            cid="follow-cid",
            value=record.model_dump(by_alias=True, exclude_none=True),
        )
        raise requests.Timeout("response lost after acceptance")

    client.com.atproto.repo.get_record.side_effect = get_record
    client.app.bsky.graph.follow.create.side_effect = create_record
    working_state = state._default_state()
    followed = follow_interactors._follow_did_list(
        client,
        working_state,
        ["did:plc:subject"],
        dry_run=False,
        action_delay_seconds=0,
    )

    assert followed == 1
    assert len(created_rkeys) == 1
    assert not working_state["follow_tracking"]["pending_follows"]
    assert state.get_follow_grace_dids(working_state, cutoff_ts=0) == {
        "did:plc:subject"
    }


def test_state_less_follow_persists_intent_and_recovers_lost_response(social_file):
    client = mock.Mock()
    client.me.did = "did:plc:bot"
    records = {}
    create_calls = []

    def get_record(params):
        response = records.get(params["rkey"])
        if response is None:
            raise BadRequestError(Response(False, 400, {"error": "RecordNotFound"}, {}))
        return response

    def create_record(*, repo, record, rkey):
        create_calls.append(rkey)
        records[rkey] = SimpleNamespace(
            uri=f"at://{repo}/app.bsky.graph.follow/{rkey}",
            cid="follow-cid",
            value=record.model_dump(by_alias=True, exclude_none=True),
        )
        raise requests.Timeout("response lost after acceptance")

    client.com.atproto.repo.get_record.side_effect = get_record
    client.app.bsky.graph.follow.create.side_effect = create_record

    assert follow_records.follow_account(client, None, "did:plc:subject", "followback")

    persisted = state.load_state()
    assert len(create_calls) == 1
    assert not persisted["follow_tracking"]["pending_follows"]
    assert len(state.get_acquisition_cohorts(persisted)["members"]) == 1


def test_starter_pack_follow_does_not_create_acquisition_cohort(social_file):
    client = mock.Mock()
    client.me.did = "did:plc:bot"
    client.com.atproto.repo.get_record.side_effect = BadRequestError(
        Response(False, 400, {"error": "RecordNotFound"}, {})
    )
    client.app.bsky.graph.follow.create.return_value = SimpleNamespace(
        uri=f"at://did:plc:bot/app.bsky.graph.follow/{follow_records._follow_rkey('did:plc:subject')}",
        cid="follow-cid",
    )

    follow_records.follow_account(
        client, state.load_state(), "did:plc:subject", "starter_pack"
    )

    latest = state.load_state()
    assert not state.get_acquisition_cohorts(latest)["members"]
    assert not state.get_follow_grace_dids(latest, cutoff_ts=0)


def test_follow_record_recovers_a_lost_local_checkpoint(social_file):
    client = mock.Mock()
    client.me.did = "did:plc:bot"
    records = {}
    create_calls = []

    def get_record(params):
        response = records.get(params["rkey"])
        if response is None:
            raise BadRequestError(Response(False, 400, {"error": "RecordNotFound"}, {}))
        return response

    def create_record(*, repo, record, rkey):
        create_calls.append(rkey)
        response = SimpleNamespace(
            uri=f"at://{repo}/app.bsky.graph.follow/{rkey}",
            cid="follow-cid",
            value=record.model_dump(by_alias=True, exclude_none=True),
        )
        records[rkey] = response
        return response

    client.com.atproto.repo.get_record.side_effect = get_record
    client.app.bsky.graph.follow.create.side_effect = create_record
    working_state = state.load_state()

    with mock.patch.object(
        follow_records.state_transactions,
        "apply",
        side_effect=state_transactions.CheckpointError("checkpoint unavailable"),
    ):
        with pytest.raises(state_transactions.CheckpointError):
            follow_records.follow_account(
                client, working_state, "did:plc:subject", "discovery"
            )

    persisted = state.load_state()
    assert set(persisted["follow_tracking"]["pending_follows"]) == {"did:plc:subject"}
    follow_records.reconcile_pending_follows(client, persisted)

    recovered = state.load_state()
    assert not recovered["follow_tracking"]["pending_follows"]
    assert len(state.get_acquisition_cohorts(recovered)["members"]) == 1
    assert state.get_follow_grace_dids(recovered, cutoff_ts=0) == {"did:plc:subject"}
    assert len(create_calls) == 1


def test_follow_record_mismatch_does_not_clear_pending_intent(social_file):
    client = mock.Mock()
    client.me.did = "did:plc:bot"
    client.com.atproto.repo.get_record.return_value = SimpleNamespace(
        uri="at://did:plc:bot/app.bsky.graph.follow/follow-wrong",
        cid="other-cid",
        value={
            "$type": "app.bsky.graph.follow",
            "createdAt": "2026-11-09T00:00:00Z",
            "subject": "did:plc:other",
        },
    )
    working_state = state.load_state()

    with pytest.raises(ValueError, match="does not match"):
        follow_records.follow_account(
            client, working_state, "did:plc:subject", "interaction"
        )

    persisted = state.load_state()
    assert set(persisted["follow_tracking"]["pending_follows"]) == {"did:plc:subject"}
    assert not state.get_acquisition_cohorts(persisted)["members"]
    client.app.bsky.graph.follow.create.assert_not_called()


def test_attribution_scan_refuses_to_replace_concurrent_scan(social_file, monkeypatch):
    stale = state.load_state()

    def collect(*args):
        state.update_state(
            lambda latest: state.get_starter_pack_attribution(latest).update(
                last_checked_at="newer"
            ),
            domains="social",
        )
        return {"observations": []}

    monkeypatch.setattr(starter_pack_attribution, "_collect_attribution", collect)
    with pytest.raises(RuntimeError, match="changed during scan"):
        starter_pack_attribution.track_starter_pack_follows(mock.Mock(), stale, False)
    assert (
        state.get_starter_pack_attribution(state.load_state())["last_checked_at"]
        == "newer"
    )


def test_dry_run_likes_never_write_state(social_file):
    before = social_file.read_bytes()
    client = mock.Mock()
    client.app.bsky.notification.list_notifications.return_value = SimpleNamespace(
        notifications=[{"reason": "reply", "uri": "candidate", "cid": "cid"}],
        cursor=None,
    )
    assert interaction_likes.like_replies(client, state.load_state(), True, 0) == 1
    assert social_file.read_bytes() == before
    client.like.assert_not_called()


def test_completed_attribution_scan_preserves_other_social_fields(
    social_file, monkeypatch
):
    stale = state.load_state()
    state.update_state(
        lambda latest: state.record_liked_reply_uri(latest, "other-like"),
        domains="social",
    )
    scan = {
        "coverage_started_at": "2026-10-27T00:00:00Z",
        "checked_at": "2026-10-27T12:00:00Z",
        "high_water_indexed_at": "2026-10-27T11:00:00Z",
        "boundary_notification_hashes": {"hash"},
        "observations": [{"pack_uri": "at://pack", "date": "2026-10-27"}],
        "cutoff_date": "2026-09-20",
    }
    monkeypatch.setattr(
        starter_pack_attribution, "_collect_attribution", lambda *args: scan
    )
    assert (
        starter_pack_attribution.track_starter_pack_follows(mock.Mock(), stale, False)
        == 1
    )
    latest = state.load_state()
    assert state.get_starter_pack_attribution(latest)["packs"]["at://pack"][
        "daily_counts"
    ] == {"2026-10-27": 1}
    assert state.get_liked_reply_uris(latest) == {"other-like"}
