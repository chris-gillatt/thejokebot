"""Bounded read-only transport diagnostics and safe failure reporting."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import httpx
import pytest
import requests
from atproto_client import exceptions
from atproto_client.request import Response

from scripts import check_bluesky_transport as probe


@pytest.fixture
def client(monkeypatch):
    client = mock.Mock()
    client.login.return_value = SimpleNamespace(did="did:plc:bot")
    client.com.atproto.server.get_session.return_value = SimpleNamespace(
        did="did:plc:bot"
    )
    client.get_profile.return_value = SimpleNamespace(did="did:plc:bot")
    monkeypatch.setattr(probe, "Client", mock.Mock(return_value=client))
    return client


def test_fresh_login_authenticated_session_and_bounded_reads(client):
    request = mock.Mock()
    result = probe.probe_transport(
        "native", request, "private-user", "private-password"
    )
    assert result == {
        "transport": "native",
        "success": True,
        "phase": "complete",
        "profile_reads": 3,
        "error": None,
        "http_status": None,
    }
    client.login.assert_called_once_with("private-user", "private-password")
    client.com.atproto.server.get_session.assert_called_once_with()
    assert client.get_profile.call_args_list == [mock.call("did:plc:bot")] * 3
    assert [call[0] for call in client.method_calls] == [
        "login",
        "com.atproto.server.get_session",
        "get_profile",
        "get_profile",
        "get_profile",
    ]
    request.close.assert_called_once_with()


@pytest.mark.parametrize("phase", ["login", "session", "profile"])
@pytest.mark.parametrize(
    "error,status",
    [
        (exceptions.UnauthorizedError(Response(False, 403, b"private-token", {})), 403),
        (
            exceptions.RateLimitExceededError(
                Response(False, 429, b"private-token", {})
            ),
            429,
        ),
        (exceptions.NetworkError(), None),
        (httpx.ConnectError("private-token"), None),
        (requests.Timeout("private-token"), None),
        (ValueError("private-token"), None),
    ],
)
def test_failures_report_only_phase_category_and_http_status(
    client, phase, error, status
):
    operation = {
        "login": client.login,
        "session": client.com.atproto.server.get_session,
        "profile": client.get_profile,
    }[phase]
    operation.side_effect = error
    request = mock.Mock()
    result = probe.probe_transport(
        "native", request, "private-user", "private-password"
    )
    assert result["success"] is False
    assert result["phase"] == phase
    assert result["error"] == type(error).__name__
    assert result["http_status"] == status
    assert result["profile_reads"] == 0
    assert "private" not in json.dumps(result)
    operation.assert_called_once()
    request.close.assert_called_once()


@pytest.mark.parametrize("phase", ["login", "session", "profile"])
def test_missing_or_changed_identity_cannot_pass(client, phase):
    if phase == "login":
        client.login.return_value = None
    elif phase == "session":
        client.com.atproto.server.get_session.return_value.did = "did:plc:other"
    else:
        client.get_profile.return_value.did = "did:plc:other"
    result = probe.probe_transport("native", mock.Mock(), "user", "password")
    assert result["success"] is False
    assert result["phase"] == phase
    assert result["error"] == "ValueError"


def test_later_read_failure_retains_the_actual_observed_prefix(client):
    client.get_profile.side_effect = [
        SimpleNamespace(did="did:plc:bot"),
        exceptions.NetworkError(),
    ]
    result = probe.probe_transport("native", mock.Mock(), "user", "password")
    assert result["success"] is False
    assert result["profile_reads"] == 1
    assert client.get_profile.call_count == 2


def test_unexpected_error_is_not_silently_classified_as_a_network_failure(client):
    client.login.side_effect = RuntimeError("unexpected failure")
    request = mock.Mock()
    with pytest.raises(RuntimeError, match="unexpected failure"):
        probe.probe_transport("native", request, "user", "password")
    request.close.assert_called_once()


@pytest.mark.parametrize(
    "successes,expected",
    [([True, True], 0), ([False, True], 1), ([True, False], 1), ([False, False], 1)],
)
def test_comparison_uses_distinct_transports_and_never_activates_them(
    monkeypatch, capsys, successes, expected
):
    monkeypatch.setattr(
        probe.runtime,
        "get_bluesky_credentials",
        lambda: ("private-user", "private-password"),
    )
    transport = mock.Mock()
    monkeypatch.setattr(
        probe.runtime, "_RequestsTransport", mock.Mock(return_value=transport)
    )
    request_factory = mock.Mock(side_effect=[mock.Mock(), mock.Mock()])
    monkeypatch.setattr(probe, "Request", request_factory)
    check = mock.Mock(
        side_effect=[
            {"transport": name, "success": success}
            for name, success in zip(("native", "requests"), successes)
        ]
    )
    monkeypatch.setattr(probe, "probe_transport", check)
    assert probe.main() == expected
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["decision"] == (
        "native_candidate" if expected == 0 else "retain_adapter"
    )
    assert payload["versions"]["atproto"]
    assert check.call_count == 2
    assert request_factory.call_args_list == [
        mock.call(timeout=30.0),
        mock.call(timeout=30.0, transport=transport),
    ]
    assert "private" not in captured.out + captured.err
    assert bool(captured.err) == bool(expected)


def test_invalid_credentials_fail_before_opening_any_transport(monkeypatch, capsys):
    monkeypatch.setattr(
        probe.runtime,
        "get_bluesky_credentials",
        mock.Mock(side_effect=ValueError("private-token")),
    )
    request = mock.Mock()
    monkeypatch.setattr(probe, "Request", request)
    assert probe.main() == 2
    request.assert_not_called()
    assert "private" not in capsys.readouterr().err


def test_script_entry_point_rejects_missing_credentials_without_network():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/check_bluesky_transport.py")],
        cwd=root,
        env={
            **os.environ,
            "BLUESKY_USERNAME": "",
            "BLUESKY_APP_PASSWORD": "",
            "BLUESKY_PASSWORD_SOURCE": "app_password",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert (
        result.stderr.strip()
        == "ERROR: Missing or invalid Bluesky credential configuration."
    )


def test_workflow_is_manual_main_only_and_has_no_state_or_public_writes():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/bluesky_check_transport.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "contents: read" in workflow
    assert "contents: write" not in workflow
    assert "timeout-minutes: 10" in workflow
    assert "persist-credentials: false" in workflow
    assert "group: joke_and_social_state_writer" in workflow
    assert "python scripts/check_bluesky_transport.py" in workflow
    assert "--require-hashes --only-binary=:all: -r requirements.lock" in workflow
    assert "SESSION" not in workflow
    assert "persist_workflow_state" not in workflow
