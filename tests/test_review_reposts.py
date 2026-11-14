import copy
import json
import subprocess
from datetime import timedelta, timezone
from unittest.mock import Mock

import pytest

from thejokebot import repost_reviews as reviews
from thejokebot import state
from thejokebot.commands import review_reposts as command
from test_repost_reviews import (
    AUTHOR,
    BOT,
    NOW,
    post,
    proposal,
    record,
    save_review,
)
from test_repost_reviews import account as account


def issue(candidate, **changes):
    return {
        "id": 1234,
        "number": 123,
        "title": command.review_title(candidate),
        "body": command.review_body(candidate),
        "user": {"id": command.ACTIONS_BOT_ID},
        "created_at": NOW.isoformat(),
        "closed_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
        "state": "closed",
        "state_reason": "completed",
        "closed_by": {"id": 42},
        **changes,
    }


def event(review_issue, action="closed", **changes):
    return {
        "repository": {"id": command.REPOSITORY_ID, "full_name": command.REPOSITORY},
        "action": action,
        "issue": copy.deepcopy(review_issue),
        "sender": {"id": 42, "login": "maintainer", "type": "User"},
        **changes,
    }


def bind(candidate):
    candidate = {
        **candidate,
        "issue_id": 1234,
        "issue_number": 123,
        "review_ready_at": NOW.isoformat(),
    }
    save_review(candidate)
    reviews.update_review(state.load_state(), candidate["key"], status="proposed")
    return candidate


@pytest.fixture
def github(monkeypatch):
    api = Mock()
    monkeypatch.setattr(command, "github_api", api)
    return api


def test_authorised_completed_review_publishes_and_confirms_in_issue(account, github):
    candidate = bind(proposal(account))
    review_issue = issue(candidate)
    github.side_effect = [
        review_issue,
        {"permission": "admin", "user": {"id": 42}},
        {"id": 99},
    ]
    command.handle_event(account, state.load_state(), event(review_issue), NOW)
    assert (
        state.load_state()["repost_reviews"]["candidates"][candidate["key"]]["status"]
        == "published"
    )
    assert account.repost.call_count == 1
    assert "Confirmed" in github.call_args.args[2]["body"]


@pytest.mark.parametrize(
    "failure",
    ["permission", "actor-id", "repository", "stale", "reopened", "not-ready"],
)
def test_untrusted_or_stale_closure_never_publishes(account, github, failure):
    candidate = bind(proposal(account))
    review_issue = issue(candidate)
    payload = event(review_issue)
    permission = {"permission": "read", "user": {"id": 42}}
    if failure == "actor-id":
        permission = {"permission": "admin", "user": {"id": 999}}
    elif failure == "repository":
        payload["repository"]["id"] = 999
    elif failure == "stale":
        review_issue["updated_at"] = "2026-11-14T10:00:00Z"
    elif failure == "reopened":
        review_issue["state"] = "open"
    elif failure == "not-ready":
        review_issue["closed_at"] = "2026-11-14T08:00:00Z"
    github.side_effect = [review_issue, permission]
    with pytest.raises(ValueError):
        command.handle_event(account, state.load_state(), payload, NOW)
    account.repost.assert_not_called()


def test_not_planned_rejects_without_reposting(account, github):
    candidate = bind(proposal(account))
    review_issue = issue(candidate, state_reason="not_planned")
    github.side_effect = [
        review_issue,
        {"permission": "write", "user": {"id": 42}},
        {"id": 99},
    ]
    command.handle_event(account, state.load_state(), event(review_issue), NOW)
    assert (
        state.load_state()["repost_reviews"]["candidates"][candidate["key"]]["status"]
        == "rejected"
    )
    account.repost.assert_not_called()


def test_issue_body_cannot_change_approved_post(account, github):
    candidate = bind(proposal(account))
    review_issue = issue(candidate, body="Repost somebody else's post instead")
    github.side_effect = [
        review_issue,
        {"permission": "maintain", "user": {"id": 42}},
        {"id": 99},
    ]
    command.handle_event(account, state.load_state(), event(review_issue), NOW)
    assert account.repost.call_args.kwargs["uri"] == candidate["post"]["uri"]


def test_existing_bot_review_is_recovered_without_creating_another(account, github):
    candidate = proposal(account)
    reviews.checkpoint_discovery(
        state.load_state(),
        {
            "inventory": reviews.read_inventory(account, NOW),
            "candidates": [candidate],
            "source_dids": [AUTHOR],
            "source_offset": 0,
        },
    )
    existing = issue(candidate, state="open", closed_at=None)
    github.side_effect = [
        {"total_count": 1, "incomplete_results": False, "items": [existing]},
        existing,
    ]
    command.deliver_reviews(state.load_state())
    assert all(call.args[1:2] in ((), ("GET",)) for call in github.call_args_list)
    assert (
        state.load_state()["repost_reviews"]["candidates"][candidate["key"]]["issue_id"]
        == 1234
    )


def test_review_text_and_images_cannot_inject_mentions_or_markup(account):
    candidate = proposal(account)
    candidate["post"]["text"] = "```\n@maintainer\n![unsafe](https://evil.test/image)"
    candidate["post"]["images"] = [
        {"url": "https://cdn.bsky.app/img/test.jpg", "alt": ""}
    ]
    body = command.review_body(candidate)
    assert "\n    @maintainer\n" in body
    assert "\n    ![unsafe]" in body
    assert "![Original post image](https://cdn.bsky.app/img/test.jpg)" in body


def test_image_only_report_becomes_a_removal_review(account, github):
    account.get_posts.side_effect = None
    account.get_posts.return_value = {
        "posts": [
            post(
                record={**post()["record"], "text": ""},
                embed={
                    "$type": "app.bsky.embed.images#view",
                    "images": [
                        {"fullsize": "https://cdn.bsky.app/img/reported.jpg", "alt": ""}
                    ],
                },
            )
        ]
    }
    report_issue = {
        "id": 1234,
        "number": 123,
        "title": "[Repost report] Unsuitable image",
        "body": f"### Original Bluesky post\n\n{post()['uri']}\n\n### Reason\n\nPlease review",
        "created_at": NOW.isoformat(),
    }
    github.side_effect = [report_issue, {"id": 99, "created_at": NOW.isoformat()}]
    command.handle_event(
        account, state.load_state(), event(report_issue, "opened"), NOW
    )
    saved = list(state.load_state()["repost_reviews"]["candidates"].values())
    assert len(saved) == 1
    assert saved[0]["action"] == "remove"
    assert saved[0]["repost_uri"] == record()["uri"]
    assert "https://cdn.bsky.app/img/reported.jpg" in github.call_args.args[2]["body"]
    account.delete_repost.assert_not_called()


def test_approved_report_deletes_only_bot_repost_and_updates_stats(account, github):
    candidate = proposal(account)
    candidate.update(
        {
            "key": "report-1234",
            "action": "remove",
            "post": {
                **candidate["post"],
                "uri": post()["uri"],
                "cid": post()["cid"],
            },
            "repost_uri": record()["uri"],
            "repost_cid": record()["cid"],
        }
    )
    candidate = bind(candidate)
    account.com.atproto.repo.get_record.return_value = record()
    account.delete_repost.return_value = True
    review_issue = issue(candidate)
    github.side_effect = [
        review_issue,
        {"permission": "admin", "user": {"id": 42}},
        {"id": 99},
    ]
    command.handle_event(account, state.load_state(), event(review_issue), NOW)
    account.delete_repost.assert_called_once_with(
        f"at://{BOT}/app.bsky.feed.repost/share"
    )
    assert (
        command.dashboard_reposts.collect(state.load_state(), NOW)["confirmed_removals"]
        == 1
    )
    account.repost.assert_not_called()


def test_confirmation_comment_failure_can_recover_without_reposting(account, github):
    candidate = bind(proposal(account))
    review_issue = issue(candidate)
    permission = {"permission": "admin", "user": {"id": 42}}
    github.side_effect = [review_issue, permission, RuntimeError("comment unavailable")]
    with pytest.raises(RuntimeError, match="comment unavailable"):
        command.handle_event(account, state.load_state(), event(review_issue), NOW)
    github.side_effect = [review_issue, permission, {"id": 99}]
    command.handle_event(account, state.load_state(), event(review_issue), NOW)
    saved = state.load_state()["repost_reviews"]["candidates"][candidate["key"]]
    assert saved["confirmation_comment_id"] == 99
    assert account.repost.call_count == 1


@pytest.mark.parametrize(
    "untrusted", ["user-owned", "edited-proposal", "ambiguous-search"]
)
def test_delivery_will_not_adopt_an_untrusted_or_ambiguous_issue(
    account, github, untrusted
):
    candidate = proposal(account)
    reviews.checkpoint_discovery(
        state.load_state(),
        {
            "inventory": reviews.read_inventory(account, NOW),
            "candidates": [candidate],
            "source_dids": [AUTHOR],
            "source_offset": 0,
        },
    )
    existing = issue(candidate)
    if untrusted == "user-owned":
        existing["user"]["id"] = 42
    else:
        existing["body"] = "Changed proposal"
    github.side_effect = [
        {
            "total_count": 2 if untrusted == "ambiguous-search" else 1,
            "incomplete_results": False,
            "items": [existing],
        },
        existing,
    ]
    with pytest.raises(ValueError):
        command.deliver_reviews(state.load_state(), NOW)
    assert not state.load_state()["repost_reviews"]["candidates"][candidate["key"]].get(
        "issue_id"
    )
    account.repost.assert_not_called()


def test_new_review_is_created_and_bound_before_it_can_publish(account, github):
    candidate = proposal(account)
    reviews.checkpoint_discovery(
        state.load_state(),
        {
            "inventory": reviews.read_inventory(account, NOW),
            "candidates": [candidate],
            "source_dids": [AUTHOR],
            "source_offset": 0,
        },
    )
    github.side_effect = [
        {"total_count": 0, "incomplete_results": False, "items": []},
        issue(candidate, state="open", closed_at=None),
    ]
    command.deliver_reviews(state.load_state(), NOW)
    saved = state.load_state()["repost_reviews"]["candidates"][candidate["key"]]
    assert saved["status"] == "proposed"
    assert saved["issue_id"] == 1234
    assert github.call_args.args[1] == "POST"
    account.repost.assert_not_called()


def test_expired_reviews_close_without_touching_account(account, github):
    candidate = bind(proposal(account))
    github.return_value = {"id": 1234}
    command.expire_reviews(state.load_state(), NOW + timedelta(days=7))
    assert github.call_args.args[2] == {
        "state": "closed",
        "state_reason": "not_planned",
    }
    assert (
        state.load_state()["repost_reviews"]["candidates"][candidate["key"]]["status"]
        == "expired"
    )
    command.expire_reviews(state.load_state(), NOW + timedelta(days=8))
    assert github.call_count == 1
    account.repost.assert_not_called()


def test_expired_undelivered_review_does_not_create_issue(account, github):
    candidate = proposal(account)
    save_review(candidate)
    reviews.update_review(state.load_state(), candidate["key"], status="proposed")
    command.deliver_reviews(state.load_state(), NOW + timedelta(days=7))
    github.assert_not_called()


@pytest.mark.parametrize(
    "source",
    [
        "https://bsky.app/profile/author.test/post/joke",
        "https://bsky.app/profile/did:plc:author/post/joke",
    ],
)
def test_report_links_resolve_to_owned_repost_only(account, github, source):
    report_issue = {
        "id": 1234,
        "number": 123,
        "title": "[Repost report] Review",
        "body": f"### Original Bluesky post\n\n{source}",
        "created_at": NOW.isoformat(),
    }
    account.com.atproto.identity.resolve_handle.return_value = {"did": AUTHOR}
    github.side_effect = [report_issue, {"id": 99, "created_at": NOW.isoformat()}]
    command.handle_event(
        account, state.load_state(), event(report_issue, "opened"), NOW
    )
    assert (
        list(state.load_state()["repost_reviews"]["candidates"].values())[0]["post"][
            "uri"
        ]
        == post()["uri"]
    )
    account.delete_repost.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [
        "No post field",
        "### Original Bluesky post\n\nhttps://evil.test/post/joke",
        "### Original Bluesky post\n\nat://did:plc:other/app.bsky.feed.post/joke",
        "### Original Bluesky post\n\nhttps://bsky.app/profile/bad@handle/post/joke",
    ],
)
def test_invalid_or_unowned_report_cannot_queue_a_removal(account, github, body):
    report_issue = {
        "id": 1234,
        "number": 123,
        "title": "[Repost report] Review",
        "body": body,
    }
    github.return_value = report_issue
    with pytest.raises(ValueError):
        command.handle_event(
            account, state.load_state(), event(report_issue, "opened"), NOW
        )
    assert state.load_state()["repost_reviews"]["candidates"] == {}
    account.delete_repost.assert_not_called()


@pytest.mark.parametrize("mode", ["preview", "inventory", "discover", "issue"])
def test_cli_routes_modes_and_preview_never_writes_social_state(
    account, github, monkeypatch, tmp_path, mode
):
    monkeypatch.setattr("sys.argv", ["review-reposts", "--mode", mode])
    monkeypatch.setattr(command, "login_client", lambda: (account, None))
    monkeypatch.setattr(command, "AGENT_TMP_DIR", tmp_path)
    monkeypatch.setattr(
        reviews, "utc_now", lambda value=None: (value or NOW).astimezone(timezone.utc)
    )
    before = state.load_state()
    payload = {"action": "closed"}
    handler = Mock()
    if mode == "issue":
        path = tmp_path / "event.json"
        path.write_text(json.dumps(payload))
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(path))
        monkeypatch.setattr(command, "handle_event", handler)
    elif mode == "discover":
        monkeypatch.setattr(command, "expire_reviews", Mock())
        monkeypatch.setattr(command, "deliver_reviews", Mock())
    elif mode == "inventory":
        monkeypatch.setenv("BLUESKY_REPOSTS_ENABLED", "false")
    command.main()
    if mode == "preview":
        assert state.load_state() == before
        assert (
            json.loads((tmp_path / "repost_preview.json").read_text())["metrics"][
                "windows"
            ]["all"]["total"]
            == 1
        )
        assert (
            "No review issues or account actions"
            in (tmp_path / "repost_preview.html").read_text()
        )
        github.assert_not_called()
    elif mode == "issue":
        handler.assert_called_once_with(account, before, payload)
    else:
        assert state.load_state()["repost_reviews"]["inventory"]["entries"]
        if mode == "inventory":
            assert state.load_state()["repost_reviews"]["candidates"] == {}
            account.get_author_feed.assert_not_called()
            github.assert_not_called()
    account.repost.assert_not_called()


@pytest.mark.parametrize(
    "response", ["success", "api-error", "timeout", "invalid-shape"]
)
def test_github_transport_surfaces_errors_and_preserves_json_requests(
    monkeypatch, response
):
    run = Mock(
        return_value=subprocess.CompletedProcess([], 0, stdout='{"id":123}', stderr="")
    )
    if response == "api-error":
        run.side_effect = subprocess.CalledProcessError(
            1, ["gh"], stderr="permission denied"
        )
    elif response == "timeout":
        run.side_effect = subprocess.TimeoutExpired(["gh"], 60)
    elif response == "invalid-shape":
        run.return_value.stdout = "[]"
    monkeypatch.setattr(command.subprocess, "run", run)
    if response == "success":
        assert command.github_api("/test", "POST", {"body": "untrusted; $(text)"}) == {
            "id": 123
        }
        assert json.loads(run.call_args.kwargs["input"])["body"] == "untrusted; $(text)"
        arguments = run.call_args.args[0]
        assert arguments[-2:] == ["--", "/test"]
        assert arguments.index("--input") < arguments.index("--")
    else:
        with pytest.raises((RuntimeError, ValueError)):
            command.github_api("/test")


def test_uncertain_review_creation_is_not_blindly_repeated(account, github):
    candidate = proposal(account)
    save_review(candidate)
    reviews.update_review(state.load_state(), candidate["key"], status="proposed")
    empty = {"total_count": 0, "incomplete_results": False, "items": []}
    github.side_effect = [empty, RuntimeError("response lost")]
    with pytest.raises(RuntimeError, match="response lost"):
        command.deliver_reviews(state.load_state(), NOW)
    github.side_effect = [empty]
    with pytest.raises(ValueError, match="uncertain"):
        command.deliver_reviews(state.load_state(), NOW)
    assert sum(call.args[1:2] == ("POST",) for call in github.call_args_list) == 1


def test_confirmed_terminal_review_does_not_repeat_action_or_comment(account, github):
    candidate = bind(proposal(account))
    review_issue = issue(candidate)
    permission = {"permission": "admin", "user": {"id": 42}}
    github.side_effect = [review_issue, permission, {"id": 99}]
    command.handle_event(account, state.load_state(), event(review_issue), NOW)
    github.side_effect = [review_issue, permission]
    command.handle_event(account, state.load_state(), event(review_issue), NOW)
    assert account.repost.call_count == 1
    assert sum(call.args[1:2] == ("POST",) for call in github.call_args_list) == 1


@pytest.mark.parametrize("changed", [False, True])
def test_missing_or_changed_original_does_not_block_own_repost_removal_review(
    account, github, changed
):
    account.get_posts.side_effect = None
    account.get_posts.return_value = {"posts": [post(cid="new-cid")] if changed else []}
    report_issue = {
        "id": 1234,
        "number": 123,
        "title": "[Repost report] Review",
        "body": f"### Original Bluesky post\n\n{post()['uri']}",
    }
    github.side_effect = [report_issue, {"id": 99, "created_at": NOW.isoformat()}]
    command.handle_event(
        account, state.load_state(), event(report_issue, "opened"), NOW
    )
    saved = state.load_state()["repost_reviews"]["candidates"]["report-1234"]
    assert saved["post"]["cid"] == post()["cid"]
    assert saved["post"]["text"] == ""
    account.delete_repost.assert_not_called()


@pytest.mark.parametrize("event_kind", ["wrong-identity", "unknown", "unsupported"])
def test_unbound_or_invalid_events_cannot_trigger_account_actions(
    account, github, event_kind
):
    review_issue = issue(proposal(account))
    payload = event(review_issue, "edited" if event_kind == "unsupported" else "closed")
    if event_kind == "wrong-identity":
        review_issue["id"] = 999
    github.return_value = review_issue
    if event_kind == "unknown":
        command.handle_event(account, state.load_state(), payload, NOW)
    else:
        with pytest.raises(ValueError):
            command.handle_event(account, state.load_state(), payload, NOW)
    account.repost.assert_not_called()
    account.delete_repost.assert_not_called()


def test_preview_html_includes_escaped_image_and_thread_context(
    account, monkeypatch, tmp_path
):
    report = reviews.discover(account, state.load_state(), NOW)
    candidate = report["candidates"][0]
    candidate["post"]["text"] = "<script>alert('untrusted')</script>"
    candidate["post"]["images"] = [
        {"url": "https://cdn.bsky.app/test.jpg", "alt": '"<unsafe>'}
    ]
    candidate["context"] = [
        {**candidate["post"], "text": "The reviewed parent context"}
    ]
    monkeypatch.setattr(command, "AGENT_TMP_DIR", tmp_path)
    command._write_preview(report, state.load_state(), NOW)
    rendered = (tmp_path / "repost_preview.html").read_text()
    assert "The reviewed parent context" in rendered
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert 'alt="&quot;&lt;unsafe&gt;"' in rendered


def test_inventory_dry_run_does_not_checkpoint_or_authenticate(account, monkeypatch):
    monkeypatch.setattr("sys.argv", ["review-reposts", "--mode", "inventory"])
    monkeypatch.setenv("BLUESKY_DRY_RUN", "true")
    login = Mock()
    monkeypatch.setattr(command, "login_client", login)
    before = state.load_state()
    with pytest.raises(ValueError, match="dry run"):
        command.main()
    assert state.load_state() == before
    login.assert_not_called()


@pytest.mark.parametrize("status", ["publishing", "uncertain", "removing"])
def test_rejection_cannot_disguise_a_previous_uncertain_account_action(
    account, github, status
):
    candidate = bind(proposal(account))
    reviews.update_review(state.load_state(), candidate["key"], status=status)
    review_issue = issue(candidate, state_reason="not_planned")
    github.side_effect = [
        review_issue,
        {"permission": "admin", "user": {"id": 42}},
        {"id": 99},
    ]
    with pytest.raises(ValueError, match="reconciled"):
        command.handle_event(account, state.load_state(), event(review_issue), NOW)
    assert (
        state.load_state()["repost_reviews"]["candidates"][candidate["key"]]["status"]
        == status
    )
    account.repost.assert_not_called()
    account.delete_repost.assert_not_called()


@pytest.mark.parametrize("number", ["123/../../user", "-XDELETE", 0, True, 1.5, None])
def test_invalid_issue_numbers_are_rejected_before_any_github_request(
    account, github, number
):
    payload = event({"id": 1234, "number": number})
    with pytest.raises(ValueError, match="positive integer"):
        command.handle_event(account, state.load_state(), payload, NOW)
    github.assert_not_called()
    account.repost.assert_not_called()
    account.delete_repost.assert_not_called()


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_report_field_accepts_line_endings_and_long_horizontal_spacing(
    account, newline
):
    body = "### Original Bluesky post" + " " * 4096 + newline * 2 + post()["uri"]
    assert command._report_uri(account, body) == post()["uri"]
    account.com.atproto.identity.resolve_handle.assert_not_called()


def test_report_field_without_value_rejects_long_blank_input(account):
    body = "### Original Bluesky post" + "\n" * 30_000
    with pytest.raises(ValueError, match="no original post value"):
        command._report_uri(account, body)
