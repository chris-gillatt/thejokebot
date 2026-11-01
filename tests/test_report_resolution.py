"""Prospective report timing from durable producers to public dashboard rendering."""

import copy
import json
from datetime import datetime, timezone
from unittest import mock

import pytest

from thejokebot import moderation_state, report_transactions, state
from thejokebot.commands import dashboard_metrics, process_reports
from test_dashboard_providers import _js
from test_report_transactions import moderation_file as moderation_file

NOW = datetime(2026, 11, 1, 9, tzinfo=timezone.utc)
EPOCH = int(NOW.timestamp())
PROPOSAL = {
    "b64": "am9rZQ==",
    "source_post_uri": "at://private-post",
    "source_reply_uri": "at://private-report",
    "reporter_did": "did:plc:private-reporter",
    "reply_indexed_at": "2020-01-01T00:00:00Z",
}


def _scan(monkeypatch, proposals, timestamp=EPOCH - 3600, working=None):
    monkeypatch.setattr(report_transactions.time, "time", lambda: timestamp)
    report_transactions.scan(
        working or state.load_state(),
        {proposal["source_reply_uri"] for proposal in proposals},
        {"complete": True},
        proposals,
    )


def _resolution():
    return state.load_state()["reports"]["resolution"]


def test_observation_and_removal_round_trip_to_full_collector_without_identifiers(
    moderation_file, monkeypatch
):
    _scan(monkeypatch, [PROPOSAL])
    monkeypatch.setattr(report_transactions.time, "time", lambda: EPOCH)
    with mock.patch.object(process_reports, "_delete_post", return_value=(True, False)):
        assert (
            process_reports.delete_approved_report_posts(
                mock.Mock(), {"jokes": [PROPOSAL]}, state.load_state()
            )
            == 1
        )
    assert _resolution()["events"] == [{"resolved_at": EPOCH, "duration_seconds": 3600}]
    collected_state = state.load_state()
    original = {
        "uri": "at://did:plc:bot/app.bsky.feed.post/original",
        "record": {"text": "A different joke", "createdAt": NOW.isoformat()},
    }
    state.add_posted_joke(
        collected_state, "b3JpZ2luYWw=", "jokeapi", post_uri=original["uri"]
    )
    result = dashboard_metrics.collect_metrics(
        "bot",
        collected_state,
        now=NOW,
        fetch_profile_call=lambda *_: {
            "did": "did:plc:bot",
            "handle": "bot.bsky.social",
            "followersCount": 1,
            "followsCount": 0,
            "postsCount": 0,
        },
        fetch_post_call=lambda *_: original,
        fetch_original_posts_call=lambda *_: [original],
    )["report_resolution"]
    assert result == {
        "window_days": 30,
        "coverage_started_at": EPOCH - 3600,
        "sample_count": 1,
        "minimum_samples": 3,
        "median_seconds": None,
    }
    assert "private" not in json.dumps(result)
    assert "events" not in result
    assert "pending" not in result


def test_stale_scan_and_duplicate_deletion_cannot_restart_or_duplicate_timing(
    moderation_file, monkeypatch
):
    stale = state.load_state()
    _scan(monkeypatch, [PROPOSAL])
    _scan(monkeypatch, [PROPOSAL], timestamp=EPOCH - 1800, working=stale)
    assert list(_resolution()["pending"].values()) == [EPOCH - 3600]
    monkeypatch.setattr(report_transactions.time, "time", lambda: EPOCH)
    report_transactions.receipt(stale, PROPOSAL["source_post_uri"], deleted=True)
    report_transactions.receipt(stale, PROPOSAL["source_post_uri"], deleted=True)
    _scan(monkeypatch, [PROPOSAL], timestamp=EPOCH, working=stale)
    assert len(_resolution()["events"]) == 1
    assert _resolution()["pending"] == {}
    assert _resolution()["coverage_started_at"] == EPOCH - 3600


def test_multiple_reports_for_one_post_produce_one_sample(moderation_file, monkeypatch):
    _scan(monkeypatch, [PROPOSAL])
    second = {**PROPOSAL, "b64": "b3RoZXI=", "source_reply_uri": "at://second-report"}
    _scan(monkeypatch, [second], timestamp=EPOCH - 1800)
    assert len(_resolution()["pending"]) == 1
    assert list(_resolution()["pending"].values()) == [EPOCH - 3600]


@pytest.mark.parametrize("result", [(False, True), (False, False)])
def test_failed_deletion_never_produces_a_sample(moderation_file, monkeypatch, result):
    _scan(monkeypatch, [PROPOSAL])
    monkeypatch.setattr(report_transactions.time, "time", lambda: EPOCH)
    with mock.patch.object(process_reports, "_delete_post", return_value=result):
        assert (
            process_reports.delete_approved_report_posts(
                mock.Mock(), {"jokes": [PROPOSAL]}, state.load_state()
            )
            == 0
        )
    assert _resolution()["events"] == []
    assert bool(_resolution()["pending"]) == result[1]
    assert bool(state.get_deleted_post_uris(state.load_state())) == (not result[1])


@pytest.mark.parametrize(
    "legacy_field",
    [
        "processed_notification_uris",
        "deleted_post_uris",
        "pending_proposals",
        "proposal_deliveries",
    ],
)
def test_legacy_receipts_are_never_backfilled(
    moderation_file, monkeypatch, legacy_field
):
    def legacy(latest):
        values = {
            "processed_notification_uris": [PROPOSAL["source_reply_uri"]],
            "deleted_post_uris": [PROPOSAL["source_post_uri"]],
            "pending_proposals": {report_transactions.proposal_key(PROPOSAL): PROPOSAL},
            "proposal_deliveries": {report_transactions.proposal_key(PROPOSAL): {}},
        }
        latest["reports"][legacy_field] = values[legacy_field]

    state.update_state(legacy, domains="moderation")
    _scan(monkeypatch, [PROPOSAL])
    assert _resolution()["pending"] == {}
    report_transactions.receipt(state.load_state(), "at://legacy", deleted=True)
    assert _resolution()["events"] == []


def test_outbox_delivery_does_not_start_a_timer(moderation_file):
    report_transactions.enqueue_proposals(state.load_state(), [PROPOSAL])
    assert _resolution()["coverage_started_at"] is None
    assert _resolution()["pending"] == {}


def test_dry_run_with_a_new_proposal_does_not_start_timing(
    moderation_file, tmp_path, monkeypatch
):
    before = moderation_file.read_bytes()
    monkeypatch.setenv("BLUESKY_REPORT_OUTPUT", str(tmp_path / "preview.json"))
    monkeypatch.setattr(process_reports, "login_client", lambda: (mock.Mock(), "bot"))
    monkeypatch.setattr(
        process_reports, "get_runtime_controls", lambda: {"dry_run": True}
    )
    monkeypatch.setattr(
        process_reports.joke_denylist, "load_denylist", lambda: {"jokes": []}
    )
    monkeypatch.setattr(
        process_reports,
        "collect_report_proposals",
        lambda *_: ([PROPOSAL], {PROPOSAL["source_reply_uri"]}, 1),
    )
    process_reports.main()
    assert moderation_file.read_bytes() == before
    assert _resolution()["coverage_started_at"] is None


def test_later_deletion_exception_cannot_discard_completed_timing(
    moderation_file, monkeypatch
):
    second = {
        **PROPOSAL,
        "b64": "c2Vjb25k",
        "source_reply_uri": "at://second-report",
        "source_post_uri": "at://second-post",
    }
    _scan(monkeypatch, [PROPOSAL, second])
    monkeypatch.setattr(report_transactions.time, "time", lambda: EPOCH)
    with (
        mock.patch.object(
            process_reports,
            "_delete_post",
            side_effect=[(True, False), RuntimeError("later failure")],
        ),
        pytest.raises(RuntimeError, match="later failure"),
    ):
        process_reports.delete_approved_report_posts(
            mock.Mock(), {"jokes": [PROPOSAL, second]}, state.load_state()
        )
    assert _resolution()["events"] == [{"resolved_at": EPOCH, "duration_seconds": 3600}]
    assert len(_resolution()["pending"]) == 1


def test_clock_regression_preserves_deletion_without_inventing_a_duration(
    moderation_file, monkeypatch, capsys
):
    _scan(monkeypatch, [PROPOSAL])
    monkeypatch.setattr(report_transactions.time, "time", lambda: EPOCH - 7200)
    report_transactions.receipt(
        state.load_state(), PROPOSAL["source_post_uri"], deleted=True
    )
    assert _resolution()["events"] == []
    assert PROPOSAL["source_post_uri"] in state.get_deleted_post_uris(
        state.load_state()
    )
    assert "clock moved backwards" in capsys.readouterr().out


def test_completed_samples_are_bounded_without_pruning_pending_timers(monkeypatch):
    working = state._default_state()
    resolution = working["reports"]["resolution"]
    resolution["pending"] = {"unrelated": 10}
    monkeypatch.setattr(moderation_state, "MAX_DEDUPE_ENTRIES", 2)
    for index in range(3):
        state.record_report_observation(working, str(index), 10)
        state.record_report_removal(working, str(index), 20 + index, successful=True)
    assert [event["resolved_at"] for event in resolution["events"]] == [21, 22]
    assert resolution["pending"] == {"unrelated": 10}


def test_rolling_completion_window_exact_threshold_and_median():
    working = state._default_state()
    resolution = working["reports"]["resolution"]
    resolution["coverage_started_at"] = EPOCH - 40 * 86400
    resolution["events"] = [
        {"resolved_at": EPOCH - 30 * 86400 - 1, "duration_seconds": 999},
        {"resolved_at": EPOCH - 30 * 86400, "duration_seconds": 100},
        {"resolved_at": EPOCH, "duration_seconds": 300},
    ]
    before = copy.deepcopy(working)
    result = dashboard_metrics._report_resolution_metrics(working, NOW)
    assert result["sample_count"] == 2
    assert result["median_seconds"] is None
    assert working == before
    resolution["events"].append({"resolved_at": EPOCH, "duration_seconds": 200})
    assert (
        dashboard_metrics._report_resolution_metrics(working, NOW)["median_seconds"]
        == 200
    )
    resolution["events"].append({"resolved_at": EPOCH, "duration_seconds": 400})
    assert (
        dashboard_metrics._report_resolution_metrics(working, NOW)["median_seconds"]
        == 250
    )


@pytest.mark.parametrize(
    "event",
    [
        None,
        {},
        {"resolved_at": True, "duration_seconds": 1},
        {"resolved_at": EPOCH, "duration_seconds": False},
        {"resolved_at": EPOCH + 1, "duration_seconds": 1},
        {"resolved_at": EPOCH, "duration_seconds": -1},
        {"resolved_at": EPOCH, "duration_seconds": 7200},
    ],
)
def test_invalid_timing_fails_explicitly(event):
    working = {
        "reports": {
            "resolution": {
                "coverage_started_at": EPOCH - 3600,
                "events": [event],
            }
        }
    }
    with pytest.raises(ValueError, match="report-resolution"):
        dashboard_metrics._report_resolution_metrics(working, NOW)


@pytest.mark.parametrize(
    "coverage,events",
    [
        (True, []),
        (EPOCH + 1, []),
        (None, {}),
        (None, [{"resolved_at": EPOCH, "duration_seconds": 1}]),
    ],
)
def test_invalid_coverage_fails_explicitly(coverage, events):
    with pytest.raises(ValueError, match="report-resolution"):
        dashboard_metrics._report_resolution_metrics(
            {
                "reports": {
                    "resolution": {"coverage_started_at": coverage, "events": events}
                }
            },
            NOW,
        )


@pytest.mark.parametrize(
    "samples,median_seconds", [(0, None), (2, None), (3, 3600), (4, 0)]
)
def test_dashboard_renders_collecting_and_measured_durations(samples, median_seconds):
    resolution = {
        "sample_count": samples,
        "minimum_samples": 3,
        "median_seconds": median_seconds,
        "coverage_started_at": EPOCH - 3600,
        "window_days": 30,
    }
    rendered = _js(
        "(()=>{metrics={report_resolution:input};renderModerationActivity();"
        "return {median:get('moderation-resolution-median').textContent,"
        "note:get('moderation-resolution-note').textContent};})()",
        resolution,
        controller=True,
    )
    assert rendered["median"] == (
        "Collecting"
        if median_seconds is None
        else "1 hr"
        if median_seconds
        else "0 sec"
    )
    assert f"{samples} timed approved-post removals" in rendered["note"]
    assert "last 30 days; median requires 3" in rendered["note"]
    assert "Timing observed since" in rendered["note"]


def test_dashboard_old_metrics_show_collecting_not_zero():
    rendered = _js(
        "(()=>{metrics={};renderModerationActivity();"
        "return [get('moderation-resolution-median').textContent,"
        "get('moderation-resolution-note').textContent];})()",
        {},
        controller=True,
    )
    assert rendered[0] == "Collecting"
    assert "Timing starts with the next report scan." in rendered[1]
