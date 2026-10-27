"""Known-pack membership checks must never turn incomplete reads into absence."""

import copy
import json
import sys
from types import SimpleNamespace
from unittest import mock

import pytest
import requests

from thejokebot import starter_pack_membership as membership
from thejokebot.commands import inspect_starter_packs as command

PACK = "at://did:plc:creator/app.bsky.graph.starterpack/pack"
LIST = "at://did:plc:creator/app.bsky.graph.list/list"
BOT = "did:plc:bot"


def _state(*uris):
    return {
        "follow_tracking": {
            "starter_pack_attribution": {"packs": {uri: {} for uri in uris}}
        }
    }


def _page(dids=(), cursor=None, uri=LIST):
    return {
        "list": {"uri": uri},
        "items": [{"subject": {"did": did}} for did in dids],
        "cursor": cursor,
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(membership, "retry_network_call", lambda fn, description: fn())
    client = mock.Mock()
    client.me.did = BOT
    client.app.bsky.graph.get_starter_pack.return_value = {
        "starterPack": {"uri": PACK, "record": {"list": LIST}, "list": {"uri": LIST}}
    }
    client.app.bsky.graph.get_list.return_value = _page()
    return client


def test_explicit_candidates_are_prioritised_and_deduplicated():
    uris, invalid = membership.candidate_uris(
        _state(PACK, "invalid"), [PACK + "2", PACK]
    )
    assert uris == [PACK + "2", PACK] and invalid == 1
    with pytest.raises(ValueError):
        membership.candidate_uris({}, ["https://bsky.app/starter-pack/not-an-at-uri"])


def test_zero_candidates_makes_no_graph_reads(client):
    report = membership.inspect_membership(client, {})
    assert report["candidate_count"] == 0 and report["results"] == []
    assert report["complete_reverse_lookup"] is False
    client.app.bsky.graph.get_starter_pack.assert_not_called()


def test_membership_found_on_second_page(client):
    source = _state(PACK)
    before = copy.deepcopy(source)
    client.app.bsky.graph.get_list.side_effect = [
        _page(["did:plc:other"], "next"),
        _page([BOT], "more"),
    ]
    report = membership.inspect_membership(client, source)
    assert report["results"][0]["status"] == "member"
    assert report["results"][0]["pages_checked"] == 2
    assert report["inclusion_dates_known"] is False
    assert source == before
    client.app.bsky.graph.get_list.assert_called_with(
        {"list": LIST, "limit": 100, "cursor": "next"}
    )
    assert "did:plc:other" not in json.dumps(report)
    client.send_post.assert_not_called()
    client.follow.assert_not_called()


def test_absence_requires_complete_list(client):
    client.app.bsky.graph.get_list.side_effect = [
        _page([], "next"),
        _page(["did:plc:other"]),
    ]
    report = membership.inspect_membership(client, _state(PACK))
    assert report["counts"]["not_member"] == 1
    assert report["all_candidates_classified"] is True


@pytest.mark.parametrize("record_only", [True, False])
def test_sdk_models_allow_either_valid_list_reference(client, record_only):
    pack = SimpleNamespace(
        uri=PACK,
        record={"list": LIST} if record_only else {},
        list=None if record_only else SimpleNamespace(uri=LIST),
    )
    client.app.bsky.graph.get_starter_pack.return_value = SimpleNamespace(
        starter_pack=pack
    )
    report = membership.inspect_membership(client, _state(PACK))
    assert report["counts"]["not_member"] == 1


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("repeat", "invalid_or_repeated_cursor"),
        ("invalid_cursor", "invalid_or_repeated_cursor"),
        ("cap", "page_limit"),
    ],
)
def test_incomplete_pagination_is_unknown(client, monkeypatch, mode, reason):
    monkeypatch.setattr(membership, "MAX_LIST_PAGES", 2)
    cursors = (
        ["same", "same"]
        if mode == "repeat"
        else ([4] if mode == "invalid_cursor" else ["one", "two"])
    )
    client.app.bsky.graph.get_list.side_effect = [
        _page([], cursor) for cursor in cursors
    ]
    result = membership.inspect_membership(client, _state(PACK))["results"][0]
    assert result["status"] == "unknown" and result["reason"] == reason


@pytest.mark.parametrize(
    "mode", ["pack_uri", "list_uri", "disagree", "missing_list", "items", "member"]
)
def test_malformed_or_mismatched_responses_are_unknown(client, mode):
    pack = client.app.bsky.graph.get_starter_pack.return_value["starterPack"]
    page = _page()
    if mode == "pack_uri":
        pack["uri"] = PACK + "wrong"
    elif mode == "list_uri":
        page["list"]["uri"] = LIST + "wrong"
    elif mode == "disagree":
        pack["record"]["list"] = LIST + "different"
    elif mode == "missing_list":
        del pack["list"]
        pack["record"] = {}
    elif mode == "items":
        page["items"] = None
    else:
        page["items"] = [{"subject": {}}]
    client.app.bsky.graph.get_list.return_value = page
    report = membership.inspect_membership(client, _state(PACK))
    assert report["counts"]["unknown"] == 1
    assert report["counts"]["not_member"] == 0


def test_failed_second_page_retains_unknown_and_checked_page_count(client):
    client.app.bsky.graph.get_list.side_effect = [
        _page([], "next"),
        requests.RequestException("offline"),
    ]
    result = membership.inspect_membership(client, _state(PACK))["results"][0]
    assert result["status"] == "unknown" and result["pages_checked"] == 1


def test_pack_read_failure_is_unknown(client):
    client.app.bsky.graph.get_starter_pack.side_effect = requests.RequestException(
        "missing or unavailable"
    )
    result = membership.inspect_membership(client, _state(PACK))["results"][0]
    assert result["status"] == "unknown" and result["pages_checked"] == 0


def test_candidate_cap_exposes_unchecked_packs(client, monkeypatch):
    monkeypatch.setattr(membership, "MAX_PACKS", 1)
    report = membership.inspect_membership(client, _state(PACK, PACK + "2"))
    assert report["not_checked"] == 1 and report["all_candidates_classified"] is False


def test_runtime_budget_stops_before_next_list_request(client, monkeypatch):
    clock = [0]
    monkeypatch.setattr(membership.time, "monotonic", lambda: clock[0])
    pack = client.app.bsky.graph.get_starter_pack.return_value

    def read(params):
        clock[0] = 61
        return pack

    client.app.bsky.graph.get_starter_pack.side_effect = read
    report = membership.inspect_membership(client, _state(PACK, PACK + "2"))
    assert report["results"][0]["reason"] == "runtime_limit"
    assert report["not_checked"] == 1
    client.app.bsky.graph.get_list.assert_not_called()


def test_retry_cannot_start_network_read_after_budget(client, monkeypatch):
    clock = [0]
    monkeypatch.setattr(membership.time, "monotonic", lambda: clock[0])

    def delayed_retry(fn, description):
        clock[0] = 61
        return fn()

    monkeypatch.setattr(membership, "retry_network_call", delayed_retry)
    result = membership.inspect_membership(client, _state(PACK))["results"][0]
    assert result["reason"] == "runtime_limit"
    client.app.bsky.graph.get_starter_pack.assert_not_called()


def test_missing_authenticated_did_is_rejected(client):
    client.me.did = None
    with pytest.raises(ValueError):
        membership.inspect_membership(client, _state(PACK))


def test_cli_writes_only_report_and_accepts_explicit_unobserved_pack(
    client, tmp_path, monkeypatch, capsys
):
    output = tmp_path / "report.json"
    state = {}
    monkeypatch.setattr(sys, "argv", ["inspect"])
    monkeypatch.setattr(command, "OUTPUT_PATH", output)
    monkeypatch.setenv("BLUESKY_INSPECT_PACK_URI", PACK)
    monkeypatch.setattr(command.bot_state, "load_state", lambda: state)
    monkeypatch.setattr(command, "login_client", lambda: (client, "bot"))
    with (
        mock.patch.object(command.bot_state, "save_state") as save,
        mock.patch.object(command.bot_state, "update_state") as update,
    ):
        command.main()
    report = json.loads(output.read_text())
    assert report["candidate_count"] == 1
    assert report["counts"]["not_member"] == 1
    assert state == {}
    assert json.loads(capsys.readouterr().out) == report
    save.assert_not_called()
    update.assert_not_called()


def test_cli_rejects_invalid_input_before_login(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["inspect", "--pack-uri", "bad"])
    monkeypatch.delenv("BLUESKY_INSPECT_PACK_URI", raising=False)
    with mock.patch.object(command, "login_client") as login, pytest.raises(SystemExit):
        command.main()
    login.assert_not_called()


def test_cli_cannot_override_report_path(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["inspect", "--output", "../state/social_state.json"]
    )
    with mock.patch.object(command, "login_client") as login, pytest.raises(SystemExit):
        command.main()
    login.assert_not_called()
