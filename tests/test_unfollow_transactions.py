"""Unfollow checkpoints must preserve state written after candidate selection."""

from unittest import mock

import pytest
import requests

from thejokebot import state
from thejokebot.commands import unfollow


@pytest.fixture
def social_file(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "STATE_FILE", str(tmp_path / "bot_state.json"))
    monkeypatch.setattr(unfollow, "retry_network_call", lambda fn, description: fn())
    state.save_state(state._default_state(), domains="social")
    return tmp_path / "state" / "social_state.json"


def test_success_checkpoint_preserves_newer_social_data(social_file):
    stale = state.load_state()

    def concurrent_changes(latest):
        state.record_liked_reply_uri(latest, "at://reply/new")
        state.record_follow_grace(latest, "did:plc:protected")
        latest["follow_fellows"]["feed_offset"] = 10

    state.update_state(concurrent_changes, domains="social")
    client = mock.Mock()
    assert unfollow._unfollow_one(
        client, stale, "did:plc:old", "at://follow/old", False
    ) == (True, False)
    persisted = state.load_state()
    assert state.get_unfollowed_dids(persisted) == {"did:plc:old"}
    assert state.get_liked_reply_uris(persisted) == {"at://reply/new"}
    assert "did:plc:protected" in state.get_follow_grace_dids(persisted)
    assert persisted["follow_fellows"]["feed_offset"] == 10


def test_reconciliation_commits_grace_before_actions(social_file):
    client = mock.Mock()
    _, all_candidates, selected = unfollow._prepare_unfollow_candidates(
        {"did:plc:new": "at://follow/new"}, set(), set(), 1
    )
    assert all_candidates == selected == []
    persisted = state.load_state()
    assert "did:plc:new" in state.get_follow_grace_dids(persisted)
    assert state.get_following_snapshot_dids(persisted) == {"did:plc:new"}
    client.unfollow.assert_not_called()


def test_dry_run_never_writes_reconciliation_or_history(social_file):
    before = social_file.read_bytes()
    preview, _, _ = unfollow._prepare_unfollow_candidates(
        {"did:plc:new": "at://follow/new"}, set(), set(), 1, dry_run=True
    )
    client = mock.Mock()
    unfollow._unfollow_one(client, preview, "did:plc:old", "at://follow/old", True)
    assert social_file.read_bytes() == before
    client.unfollow.assert_not_called()


def test_partial_success_survives_throttle_without_final_save(social_file):
    client = mock.Mock()
    client.unfollow.side_effect = [None, requests.RequestException("429 throttle")]
    result = unfollow._execute_unfollow_loop(
        client,
        state.load_state(),
        ["one", "two"],
        {"one": "uri1", "two": "uri2"},
        False,
        0,
        50,
        0,
    )
    assert result == (1, 1, 0, True)
    assert state.get_unfollowed_dids(state.load_state()) == {"one"}


def test_corrupt_state_prevents_candidate_actions(social_file):
    social_file.write_text("{broken", encoding="utf-8")
    with pytest.raises(state.StateReadError):
        unfollow._prepare_unfollow_candidates({"one": "uri"}, set(), set(), 1)
    assert social_file.read_text(encoding="utf-8") == "{broken"


def test_checkpoint_failure_stops_later_actions(social_file):
    client = mock.Mock()

    def corrupt_after_action(uri):
        social_file.write_text("{broken", encoding="utf-8")

    client.unfollow.side_effect = corrupt_after_action
    with pytest.raises(state.StateReadError):
        unfollow._execute_unfollow_loop(
            client,
            state.load_state(),
            ["one", "two"],
            {"one": "uri1", "two": "uri2"},
            False,
            0,
            50,
            0,
        )
    client.unfollow.assert_called_once_with("uri1")
    assert social_file.read_text(encoding="utf-8") == "{broken"
