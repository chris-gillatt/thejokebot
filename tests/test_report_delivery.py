"""Delivery recovery against real local Git repositories and a simulated GitHub API."""

import json
import subprocess
from unittest import mock

import pytest

from thejokebot import denylist, report_transactions, state
from thejokebot.commands import create_report_prs as delivery
from thejokebot.commands import post_joke, process_reports

PROPOSAL = {
    "b64": "dGVzdA==",
    "source_provider": "jokeapi",
    "source_post_uri": "at://post/one",
    "source_reply_uri": "at://reply/one",
}


def git(directory, *args):
    return subprocess.run(
        ["git", *args], cwd=directory, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repository(tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    git(tmp_path, "init", "--bare", "--initial-branch=main", str(remote))
    git(tmp_path, "clone", str(remote), str(repo))
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    resources = repo / "resources"
    resources.mkdir()
    denylist = resources / "jokebot_denylist.json"
    jokebook = resources / "jokebot_jokebook.json"
    denylist.write_text(json.dumps({"version": 1, "jokes": []}))
    jokebook.write_text(json.dumps({"jokes": [PROPOSAL["b64"]]}))
    monkeypatch.chdir(repo)
    monkeypatch.setattr(state, "STATE_FILE", str(repo / "bot_state.json"))
    monkeypatch.setattr(delivery, "RESOURCES_DIR", resources)
    monkeypatch.setattr(delivery, "DENYLIST_PATH", denylist)
    monkeypatch.setattr(delivery, "JOKEBOOK_PATH", jokebook)
    monkeypatch.setenv("BLUESKY_REPORT_OUTPUT", str(tmp_path / "missing-artifact.json"))
    state.save_state(state._default_state(), domains="moderation")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "Initial state")
    git(repo, "push", "-u", "origin", "main")
    return repo


def queue(repo, proposal):
    report_transactions.enqueue_proposals(state.load_state(), [proposal])
    git(repo, "add", "state/moderation_state.json")
    git(repo, "commit", "-m", "Persist queued report")
    git(repo, "push", "origin", "main")


def github(monkeypatch, phase=None, initial=None):
    rows = list(initial or [])
    real_run = delivery.run_command
    failed = False
    creates = []

    def run(args, check=True):
        nonlocal failed
        if args[:3] == ["git", "push", "-u"] and phase == "before-push" and not failed:
            failed = True
            raise subprocess.CalledProcessError(1, args)
        if args[0] != "gh":
            return real_run(args, check=check)
        if args[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(rows))
        assert args[:3] == ["gh", "pr", "create"]
        if phase == "after-push" and not failed:
            failed = True
            raise subprocess.CalledProcessError(1, args)
        branch = args[args.index("--head") + 1]
        creates.append(branch)
        rows.append(
            {
                "number": 42,
                "state": "OPEN",
                "baseRefName": "main",
                "headRefName": branch,
                "isCrossRepository": False,
            }
        )
        if phase == "after-create" and not failed:
            failed = True
            raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(args, 0, stdout="created")

    monkeypatch.setattr(delivery, "run_command", run)
    return rows, creates


@pytest.mark.parametrize(
    "provider,phase",
    [
        ("jokeapi", "before-push"),
        ("jokeapi", "after-push"),
        ("jokeapi", "after-create"),
        ("jokebot_jokebook", "after-push"),
    ],
)
def test_recovery_keeps_queue_until_verified_and_never_changes_main_content(
    repository, monkeypatch, provider, phase
):
    proposal = {**PROPOSAL, "source_provider": provider}
    queue(repository, proposal)
    rows, creates = github(monkeypatch, phase)
    with pytest.raises(RuntimeError, match="delivery attempt"):
        delivery.main()
    assert len(report_transactions.pending_proposals(state.load_state())) == 1
    assert git(repository, "branch", "--show-current") == "main"
    delivery.main()
    assert report_transactions.pending_proposals(state.load_state()) == {}
    assert len(rows) == len(creates) == 1
    assert git(repository, "branch", "--show-current") == "main"
    assert json.loads(delivery.DENYLIST_PATH.read_text())["jokes"] == []
    assert json.loads(delivery.JOKEBOOK_PATH.read_text())["jokes"] == [PROPOSAL["b64"]]
    assert git(repository, "diff", "--name-only") == "state/moderation_state.json"
    delivery.main()
    assert len(creates) == 1


@pytest.mark.parametrize("provider", ["jokeapi", "jokebot_jokebook"])
@pytest.mark.parametrize("status", ["OPEN", "CLOSED", "MERGED"])
def test_existing_review_is_terminal_even_when_branch_was_deleted(
    repository, monkeypatch, status, provider
):
    proposal = {**PROPOSAL, "source_provider": provider}
    queue(repository, proposal)
    branch = delivery.branch_name_for_b64(
        proposal["b64"], delivery.proposal_target(proposal)
    )
    _, creates = github(
        monkeypatch,
        initial=[
            {
                "number": 7,
                "state": status,
                "baseRefName": "main",
                "headRefName": branch,
                "isCrossRepository": False,
            }
        ],
    )
    delivery.main()
    assert creates == []
    assert report_transactions.pending_proposals(state.load_state()) == {}
    proof = state.load_state()["reports"]["proposal_deliveries"][
        report_transactions.proposal_key(proposal)
    ]
    assert proof == {"number": 7, "state": status}


@pytest.mark.parametrize(
    "payload", [{}, [{"number": 1, "state": "OPEN", "isCrossRepository": True}]]
)
def test_invalid_api_responses_leave_queue_retryable(repository, monkeypatch, payload):
    queue(repository, PROPOSAL)
    with mock.patch.object(
        delivery,
        "run_command",
        return_value=subprocess.CompletedProcess([], 0, stdout=json.dumps(payload)),
    ):
        with pytest.raises(RuntimeError, match="delivery attempt"):
            delivery.main()
    assert len(report_transactions.pending_proposals(state.load_state())) == 1


@pytest.mark.parametrize("unexpected_file", [True, False])
def test_unexpected_orphan_branch_is_not_published(
    repository, monkeypatch, unexpected_file
):
    queue(repository, PROPOSAL)
    branch = delivery.branch_name_for_b64(PROPOSAL["b64"], "denylist")
    git(repository, "checkout", "-b", branch)
    if unexpected_file:
        (repository / "unexpected.txt").write_text("unrelated")
    else:
        delivery.DENYLIST_PATH.write_text(
            json.dumps({"version": 1, "jokes": [{"b64": "wrong"}]})
        )
    git(repository, "add", ".")
    git(repository, "commit", "-m", "Unexpected branch")
    git(repository, "push", "origin", branch)
    git(repository, "checkout", "main")
    _, creates = github(monkeypatch)
    with pytest.raises(RuntimeError, match="delivery attempt"):
        delivery.main()
    assert creates == []
    assert len(report_transactions.pending_proposals(state.load_state())) == 1


def test_cleanup_failure_aborts_and_retains_proposal(repository, monkeypatch):
    queue(repository, PROPOSAL)
    github(monkeypatch)
    with mock.patch.object(
        delivery,
        "_cleanup_local_branch",
        side_effect=subprocess.CalledProcessError(1, "checkout"),
    ):
        with pytest.raises(delivery.BranchCleanupError):
            delivery.main()
    assert len(report_transactions.pending_proposals(state.load_state())) == 1
    assert git(repository, "branch", "--show-current") != "main"


def test_scan_queues_proposal_atomically_without_persisting_reporter_text(repository):
    proposal = {
        **PROPOSAL,
        "reporter_did": "private-reporter",
        "reply_text": "private-text",
    }
    report_transactions.scan(state.load_state(), {"at://reply/one"}, {}, [proposal])
    latest = state.load_state()
    assert "at://reply/one" in state.get_processed_notification_uris(latest)
    assert len(report_transactions.pending_proposals(latest)) == 1
    text = (repository / "state/moderation_state.json").read_text()
    assert "private-reporter" not in text
    assert "private-text" not in text


def test_receipt_failure_keeps_proposal_until_next_verified_lookup(
    repository, monkeypatch
):
    queue(repository, PROPOSAL)
    _, creates = github(monkeypatch)
    with mock.patch.object(
        report_transactions, "confirm_delivery", side_effect=OSError("disk full")
    ):
        with pytest.raises(OSError):
            delivery.main()
    assert len(report_transactions.pending_proposals(state.load_state())) == 1
    delivery.main()
    assert len(creates) == 1
    assert report_transactions.pending_proposals(state.load_state()) == {}


@pytest.mark.parametrize("provider", ["jokeapi", "jokebot_jokebook"])
def test_orphan_recovery_uses_original_base_when_main_has_advanced(
    repository, monkeypatch, provider
):
    queue(repository, {**PROPOSAL, "source_provider": provider})
    _, creates = github(monkeypatch, "after-push")
    with pytest.raises(RuntimeError):
        delivery.main()
    original = json.loads(delivery.DENYLIST_PATH.read_text())
    original["jokes"].append({"b64": "another-approved-joke"})
    delivery.DENYLIST_PATH.write_text(json.dumps(original))
    git(repository, "add", "resources/jokebot_denylist.json")
    git(repository, "commit", "-m", "Another approved change")
    git(repository, "push", "origin", "main")
    delivery.main()
    assert len(creates) == 1
    assert json.loads(delivery.DENYLIST_PATH.read_text()) == original


def test_jokebook_review_includes_source_post_denylist_entry(repository, monkeypatch):
    proposal = {**PROPOSAL, "source_provider": "jokebot_jokebook"}
    queue(repository, proposal)
    github(monkeypatch)
    delivery.main()
    branch = delivery.branch_name_for_b64(proposal["b64"], "jokebook")
    paths = git(repository, "diff", "--name-only", f"main...origin/{branch}")
    assert paths.splitlines() == [
        "resources/jokebot_denylist.json",
        "resources/jokebot_jokebook.json",
    ]
    proposed = json.loads(
        git(repository, "show", f"origin/{branch}:resources/jokebot_denylist.json")
    )
    assert len(proposed["jokes"]) == 1
    assert proposed["jokes"][0]["b64"] == proposal["b64"]
    assert proposed["jokes"][0]["source_post_uri"] == proposal["source_post_uri"]
    assert json.loads(delivery.DENYLIST_PATH.read_text())["jokes"] == []
    assert json.loads(delivery.JOKEBOOK_PATH.read_text())["jokes"] == [proposal["b64"]]


@pytest.mark.parametrize("missing_joke", [False, True])
@pytest.mark.parametrize("existing_uri", [None, "at://post/one", "at://post/other"])
def test_partial_jokebook_resources_preserve_remaining_review_work(
    repository, monkeypatch, missing_joke, existing_uri
):
    proposal = {**PROPOSAL, "source_provider": "jokebot_jokebook"}
    if missing_joke:
        delivery.JOKEBOOK_PATH.write_text(json.dumps({"jokes": []}))
    if existing_uri:
        payload = denylist.load_denylist(delivery.DENYLIST_PATH)
        denylist.add_denylist_entry(
            payload,
            b64=proposal["b64"],
            source_post_uri=existing_uri,
            source_reply_uri="at://earlier-report",
            reporter_did="unknown",
        )
        denylist.save_denylist(payload, delivery.DENYLIST_PATH)
    git(repository, "add", "resources")
    git(repository, "commit", "--allow-empty", "-m", "Partial approved resources")
    git(repository, "push", "origin", "main")
    queue(repository, proposal)
    _, creates = github(monkeypatch, "after-push")
    with pytest.raises(RuntimeError, match="delivery attempt"):
        delivery.main()
    if missing_joke and existing_uri == proposal["source_post_uri"]:
        assert creates == []
        assert len(report_transactions.pending_proposals(state.load_state())) == 1
        return
    delivery.main()
    assert len(creates) == 1
    branch = creates[0]
    expected_paths = []
    if existing_uri != proposal["source_post_uri"]:
        expected_paths.append("resources/jokebot_denylist.json")
    if not missing_joke:
        expected_paths.append("resources/jokebot_jokebook.json")
    assert (
        git(repository, "diff", "--name-only", f"main...origin/{branch}").splitlines()
        == expected_paths
    )
    proposed = json.loads(
        git(repository, "show", f"origin/{branch}:resources/jokebot_denylist.json")
    )
    matching = [
        entry
        for entry in proposed["jokes"]
        if entry["source_post_uri"] == proposal["source_post_uri"]
    ]
    assert len(matching) == 1
    assert len(proposed["jokes"]) == (2 if existing_uri == "at://post/other" else 1)


@pytest.mark.parametrize(
    "tampering",
    [
        "missing-denylist",
        "missing-jokebook",
        "wrong-uri",
        "extra-file",
        "extra-entry",
        "changed-reason",
    ],
)
def test_jokebook_orphan_rejects_incomplete_or_unrelated_changes(
    repository, monkeypatch, tampering
):
    proposal = {**PROPOSAL, "source_provider": "jokebot_jokebook"}
    queue(repository, proposal)
    _, creates = github(monkeypatch, "after-push")
    with pytest.raises(RuntimeError, match="delivery attempt"):
        delivery.main()
    branch = delivery.branch_name_for_b64(proposal["b64"], "jokebook")
    git(repository, "checkout", "-b", "alter-orphan", f"origin/{branch}")
    if tampering.startswith("missing-"):
        resource = "denylist" if tampering == "missing-denylist" else "jokebook"
        git(repository, "checkout", "main", "--", f"resources/jokebot_{resource}.json")
    elif tampering == "extra-file":
        (repository / "unexpected.txt").write_text("unrelated")
    else:
        payload = denylist.load_denylist(delivery.DENYLIST_PATH)
        if tampering == "extra-entry":
            payload["jokes"].append({"b64": "unrelated"})
        elif tampering == "changed-reason":
            payload["jokes"][0]["reason"] = "different reason"
        else:
            payload["jokes"][0]["source_post_uri"] = "at://wrong-post"
        denylist.save_denylist(payload, delivery.DENYLIST_PATH)
    git(repository, "add", "resources")
    if tampering == "extra-file":
        git(repository, "add", "unexpected.txt")
    git(repository, "commit", "-m", "Alter orphan branch")
    git(repository, "push", "origin", f"HEAD:{branch}")
    git(repository, "checkout", "main")
    with pytest.raises(RuntimeError, match="delivery attempt"):
        delivery.main()
    assert creates == []
    assert len(report_transactions.pending_proposals(state.load_state())) == 1


def test_approved_jokebook_resources_delete_once_and_suppress_live_joke(
    repository, monkeypatch
):
    proposal = {**PROPOSAL, "source_provider": "jokebot_jokebook"}
    report_transactions.scan(
        state.load_state(), {proposal["source_reply_uri"]}, {}, [proposal]
    )
    github(monkeypatch)
    delivery.main()
    branch = delivery.branch_name_for_b64(proposal["b64"], "jokebook")
    with mock.patch.object(
        process_reports, "_delete_post", return_value=(True, False)
    ) as delete:
        assert (
            process_reports.delete_approved_report_posts(
                mock.Mock(),
                denylist.load_denylist(delivery.DENYLIST_PATH),
                state.load_state(),
            )
            == 0
        )
        delete.assert_not_called()
        git(repository, "merge", "--ff-only", f"origin/{branch}")
        approved = denylist.load_denylist(delivery.DENYLIST_PATH)
        assert (
            process_reports.delete_approved_report_posts(
                mock.Mock(), approved, state.load_state()
            )
            == 1
        )
        assert (
            process_reports.delete_approved_report_posts(
                mock.Mock(), approved, state.load_state()
            )
            == 0
        )
        delete.assert_called_once()
    latest = state.load_state()
    assert state.get_deleted_post_uris(latest) == {proposal["source_post_uri"]}
    assert len(latest["reports"]["resolution"]["events"]) == 1
    assert json.loads(delivery.JOKEBOOK_PATH.read_text())["jokes"] == []
    for provider in post_joke.joke_providers.PROVIDERS:
        with (
            mock.patch.dict(
                post_joke.joke_providers.PROVIDERS, {provider: lambda: "test"}
            ),
            pytest.raises(post_joke.JokeSelectionExhausted),
        ):
            post_joke.pick_joke(denylist.get_denylisted_b64s(approved), provider)


def test_jokebook_orphan_recovers_after_temporary_reporter_evidence_disappears(
    repository, monkeypatch, tmp_path
):
    proposal = {
        **PROPOSAL,
        "source_provider": "jokebot_jokebook",
        "reporter_did": "did:plc:reporter",
        "reply_text": "private report text",
    }
    artifact = tmp_path / "proposals.json"
    artifact.write_text(json.dumps({"proposals": [proposal]}))
    monkeypatch.setenv("BLUESKY_REPORT_OUTPUT", str(artifact))
    _, creates = github(monkeypatch, "after-push")
    with pytest.raises(RuntimeError, match="delivery attempt"):
        delivery.main()
    artifact.unlink()
    delivery.main()
    assert len(creates) == 1
    assert report_transactions.pending_proposals(state.load_state()) == {}


def test_fresh_evidence_cannot_replace_queued_identity():
    queued = dict(PROPOSAL)
    assert (
        delivery._with_fresh_evidence(queued, {**queued, "reply_text": "same report"})[
            "reply_text"
        ]
        == "same report"
    )
    different = {
        **queued,
        "source_reply_uri": "at://different",
        "reply_text": "different reporter",
    }
    assert delivery._with_fresh_evidence(queued, different) == queued
