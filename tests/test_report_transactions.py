"""Report receipts, retry queues and scan checkpoints under stale-state interleavings."""

import copy
from types import SimpleNamespace
from unittest import mock

import pytest
import requests

from thejokebot import report_transactions, state
from thejokebot.commands import process_reports

PROPOSAL = {
    "source_reply_uri": "at://reply",
    "reply_cid": "cid",
    "root_uri": "at://root",
    "root_cid": "root-cid",
}


@pytest.fixture
def moderation_file(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "STATE_FILE", str(tmp_path / "bot_state.json"))
    state.save_state(state._default_state(), domains="moderation")
    monkeypatch.setattr(
        process_reports, "retry_network_call", lambda fn, description, **kwargs: fn()
    )
    return tmp_path / "state" / "moderation_state.json"


def test_scan_merges_attempts_and_preserves_other_receipts(moderation_file):
    stale = state.load_state()

    def concurrent(latest):
        state.record_deleted_post_uri(latest, "other-post")
        for _ in range(2):
            state.increment_unresolved_notification_attempt(latest, "unresolved")
        state.increment_unresolved_notification_attempt(latest, "other-unresolved")

    state.update_state(concurrent, domains="moderation")
    report_transactions.scan(
        stale,
        {"processed"},
        {"attempted": ["unresolved"], "max_attempts": 3},
        [PROPOSAL],
    )
    latest = state.load_state()
    assert state.get_deleted_post_uris(latest) == {"other-post"}
    assert state.get_processed_notification_uris(latest) == {"processed", "unresolved"}
    assert state.get_unresolved_notification_attempts(latest) == {"other-unresolved": 1}
    assert "at://reply" in report_transactions.pending_acknowledgements(latest)
    assert latest["reports"]["last_checked_at"] is None


def test_processed_receipts_win_over_stale_retry_attempts(moderation_file):
    stale = state.load_state()
    state.update_state(
        lambda latest: state.record_processed_notification(latest, "done"),
        domains="moderation",
    )
    report_transactions.scan(
        stale, set(), {"attempted": ["done"], "max_attempts": 3}, []
    )
    assert state.get_unresolved_notification_attempts(state.load_state()) == {}


def test_complete_scan_timestamp_is_monotonic(moderation_file, monkeypatch):
    state.update_state(
        lambda latest: latest["reports"].update(last_checked_at=1000),
        domains="moderation",
    )
    monkeypatch.setattr(report_transactions.time, "time", lambda: 100)
    report_transactions.scan(state.load_state(), set(), {"complete": True}, [])
    assert state.load_state()["reports"]["last_checked_at"] == 1000


def test_deletion_prefix_is_saved_immediately(moderation_file):
    stale = state.load_state()
    state.update_state(
        lambda latest: state.record_acknowledged_report_uri(latest, "other-ack"),
        domains="moderation",
    )
    denylist = {"jokes": [{"source_post_uri": "one"}, {"source_post_uri": "two"}]}
    with mock.patch.object(
        process_reports, "_delete_post", side_effect=[(True, False), (False, True)]
    ):
        assert (
            process_reports.delete_approved_report_posts(mock.Mock(), denylist, stale)
            == 1
        )
    latest = state.load_state()
    assert state.get_deleted_post_uris(latest) == {"one"}
    assert state.get_acknowledged_report_uris(latest) == {"other-ack"}


def test_ack_queue_survives_processed_notifications_and_then_clears(moderation_file):
    working = state.load_state()
    report_transactions.scan(working, {"at://reply"}, {}, [PROPOSAL])
    resumed = state.load_state()
    assert "at://reply" in state.get_processed_notification_uris(resumed)
    assert (
        report_transactions.pending_acknowledgements(resumed)["at://reply"]["reply_cid"]
        == "cid"
    )
    report_transactions.receipt(resumed, "at://reply")
    report_transactions.scan(working, set(), {}, [PROPOSAL])
    latest = state.load_state()
    assert report_transactions.pending_acknowledgements(latest) == {}
    assert "at://reply" in state.get_acknowledged_report_uris(latest)


def _ack_client():
    client = mock.Mock()
    client.me.did = "did:plc:bot"
    client.get_post_thread.return_value = SimpleNamespace(
        thread=SimpleNamespace(post=SimpleNamespace(uri="at://reply"), replies=[])
    )
    return client


def test_ambiguous_ack_is_sent_once_and_next_run_recovers(moderation_file):
    working = state.load_state()
    report_transactions.scan(working, {"at://reply"}, {}, [PROPOSAL])
    client = _ack_client()
    client.send_post.side_effect = requests.RequestException("response lost")
    assert process_reports.acknowledge_report(client, PROPOSAL) == (False, True)
    assert "at://reply" in report_transactions.pending_acknowledgements(
        state.load_state()
    )
    client.get_post_thread.return_value.thread.replies = [
        SimpleNamespace(
            post=SimpleNamespace(
                author=SimpleNamespace(did=client.me.did),
                record=SimpleNamespace(text=process_reports._ACK_TEXT),
            )
        )
    ]
    assert process_reports.acknowledge_report(client, PROPOSAL) == (True, False)
    report_transactions.receipt(working, "at://reply")
    client.send_post.assert_called_once()
    assert report_transactions.pending_acknowledgements(state.load_state()) == {}


def test_other_authors_ack_text_does_not_suppress_our_ack(moderation_file):
    client = _ack_client()
    client.get_post_thread.return_value.thread.replies = [
        SimpleNamespace(
            post=SimpleNamespace(
                author=SimpleNamespace(did="did:plc:other"),
                record=SimpleNamespace(text=process_reports._ACK_TEXT),
            )
        )
    ]
    assert process_reports.acknowledge_report(client, PROPOSAL) == (True, False)
    client.send_post.assert_called_once()


def test_unverified_thread_cannot_trigger_a_post(moderation_file):
    client = _ack_client()
    client.get_post_thread.return_value.thread.post.uri = "at://wrong"
    assert process_reports.acknowledge_report(client, PROPOSAL) == (False, True)
    client.send_post.assert_not_called()


def test_corrupt_state_cannot_be_overwritten_by_receipt(moderation_file):
    working = state.load_state()
    before = copy.deepcopy(working)
    moderation_file.write_text("{broken", encoding="utf-8")
    with pytest.raises(state.StateReadError):
        report_transactions.receipt(working, "post", deleted=True)
    assert working == before
    assert moderation_file.read_text() == "{broken"


def test_dry_run_main_has_no_account_or_state_writes(
    moderation_file, tmp_path, monkeypatch
):
    before = moderation_file.read_bytes()
    client = _ack_client()
    client.app.bsky.notification.list_notifications.return_value = SimpleNamespace(
        notifications=[], cursor=None
    )
    monkeypatch.setenv("BLUESKY_REPORT_OUTPUT", str(tmp_path / "preview.json"))
    monkeypatch.setattr(process_reports, "login_client", lambda: (client, "bot"))
    monkeypatch.setattr(
        process_reports, "get_runtime_controls", lambda: {"dry_run": True}
    )
    monkeypatch.setattr(
        process_reports.joke_denylist,
        "load_denylist",
        lambda: {"jokes": [{"source_post_uri": "post"}]},
    )
    process_reports.main()
    assert moderation_file.read_bytes() == before
    client.send_post.assert_not_called()
    client.app.bsky.feed.post.delete.assert_not_called()


@pytest.mark.parametrize(
    "result,remains_pending", [((False, True), True), ((False, False), False)]
)
def test_main_retries_durable_ack_queue_without_new_notifications(
    moderation_file, tmp_path, monkeypatch, result, remains_pending
):
    report_transactions.scan(state.load_state(), {"at://reply"}, {}, [PROPOSAL])
    client = _ack_client()
    client.app.bsky.notification.list_notifications.return_value = SimpleNamespace(
        notifications=[], cursor=None
    )
    monkeypatch.setenv("BLUESKY_REPORT_OUTPUT", str(tmp_path / "proposals.json"))
    monkeypatch.setattr(process_reports, "login_client", lambda: (client, "bot"))
    monkeypatch.setattr(
        process_reports, "get_runtime_controls", lambda: {"dry_run": False}
    )
    monkeypatch.setattr(
        process_reports.joke_denylist, "load_denylist", lambda: {"jokes": []}
    )
    with mock.patch.object(
        process_reports, "acknowledge_report", return_value=result
    ) as ack:
        process_reports.main()
    ack.assert_called_once()
    assert (
        bool(report_transactions.pending_acknowledgements(state.load_state()))
        == remains_pending
    )


def test_output_failure_does_not_commit_scan_checkpoint(
    moderation_file, tmp_path, monkeypatch
):
    before = moderation_file.read_bytes()
    client = _ack_client()
    monkeypatch.setattr(process_reports, "login_client", lambda: (client, "bot"))
    monkeypatch.setattr(
        process_reports, "get_runtime_controls", lambda: {"dry_run": False}
    )
    monkeypatch.setattr(
        process_reports.joke_denylist, "load_denylist", lambda: {"jokes": []}
    )
    monkeypatch.setattr(
        process_reports,
        "collect_report_proposals",
        lambda *args: ([PROPOSAL], {"at://reply"}, 1),
    )
    with mock.patch.object(
        process_reports, "_write_output", side_effect=OSError("disk full")
    ):
        with pytest.raises(OSError):
            process_reports.main()
    assert moderation_file.read_bytes() == before
    client.send_post.assert_not_called()
