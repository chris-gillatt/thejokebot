"""Exercise social checkpoints with real state files and stale working snapshots."""

import copy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

import pytest
import requests

from thejokebot import state_transactions, state
from thejokebot.commands import follow_back, follow_interactors, interaction_likes
from thejokebot.commands import joke_requests, starter_pack_attribution


@pytest.fixture
def social_file(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "STATE_FILE", str(tmp_path / "bot_state.json"))
    state.save_state(state._default_state(), domains=("posting", "social"))
    for module in (interaction_likes, follow_back):
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
    state.update_state(
        lambda latest: state.record_liked_reply_uri(latest, "other-like"),
        domains="social",
    )
    follow_interactors._checkpoint_follow(stale, "interactor")
    follow_back._follow_candidates(
        mock.Mock(),
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
