"""Create one denylist pull request per reported joke proposal."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from thejokebot import denylist as joke_denylist
from thejokebot import report_transactions, state as bot_state
from thejokebot.paths import AGENT_TMP_DIR, RESOURCES_DIR

DEFAULT_PROPOSALS_PATH = AGENT_TMP_DIR / "report_proposals.json"
DENYLIST_PATH = RESOURCES_DIR / "jokebot_denylist.json"
JOKEBOOK_PATH = RESOURCES_DIR / "jokebot_jokebook.json"
JOKEBOOK_PROVIDER_NAME = "jokebot_jokebook"


class BranchCleanupError(RuntimeError):
    """Stop delivery if returning safely to main fails."""


def run_command(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, check=False, text=True, capture_output=True)
    if check and result.returncode != 0:
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        result.check_returncode()
    return result


def has_remote_branch(branch_name: str) -> bool:
    result = run_command(["git", "ls-remote", "--heads", "origin", branch_name])
    result.check_returncode()
    return bool(result.stdout.strip())


def find_review_pr(branch_name: str) -> dict | None:
    result = run_command(
        [
            "gh",
            "pr",
            "list",
            "--head",
            branch_name,
            "--state",
            "all",
            "--base",
            "main",
            "--json",
            "number,state,baseRefName,headRefName,isCrossRepository",
        ],
    )
    result.check_returncode()
    rows = json.loads(result.stdout)
    if not isinstance(rows, list):
        raise ValueError("Review PR lookup must return a list")
    for row in rows:
        if (
            isinstance(row.get("number"), int)
            and row["number"] > 0
            and row.get("state") in {"OPEN", "CLOSED", "MERGED"}
            and row.get("baseRefName") == "main"
            and row.get("headRefName") == branch_name
            and row.get("isCrossRepository") is False
        ):
            return row
        raise ValueError("Review PR lookup returned an unexpected PR")
    return None


def proposal_target(proposal: dict) -> str:
    """Return persistence target for a report proposal: denylist or jokebook."""
    if proposal.get("source_provider") == JOKEBOOK_PROVIDER_NAME:
        return "jokebook"
    return "denylist"


def branch_name_for_b64(b64_value: str, target: str) -> str:
    suffix = hashlib.sha1(b64_value.encode("utf-8")).hexdigest()[:12]
    if target == "jokebook":
        return f"chore/report-jokebook-{suffix}"
    return f"chore/report-denylist-{suffix}"


def _cleanup_local_branch(branch_name: str) -> None:
    """Best-effort return to main and delete temporary branch."""
    run_command(["git", "checkout", "main"])
    run_command(["git", "branch", "-D", branch_name], check=False)


def load_jokebook(file_path: Path | None = None) -> dict:
    """Load jokebook payload from disk, defaulting to an empty list."""
    path = file_path or JOKEBOOK_PATH
    if not path.exists():
        return {"jokes": []}
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        return {"jokes": []}
    payload.setdefault("jokes", [])
    return payload


def save_jokebook(payload: dict, file_path: Path | None = None) -> None:
    """Write jokebook payload atomically."""
    path = file_path or JOKEBOOK_PATH
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def remove_jokebook_entry(payload: dict, b64_value: str) -> bool:
    """Remove reported b64 entry from jokebook. Returns True when removed."""
    jokes = payload.get("jokes", [])
    filtered = [j for j in jokes if j != b64_value]
    if len(filtered) == len(jokes):
        return False
    payload["jokes"] = filtered
    return True


def _markdown_fence_for(*values: str) -> str:
    longest_run = 0
    for value in values:
        current_run = 0
        for character in value:
            if character == "`":
                current_run += 1
                longest_run = max(longest_run, current_run)
            else:
                current_run = 0
    return "`" * max(3, longest_run + 1)


def build_pr_body(proposal: dict, joke_hash: str) -> str:
    reply_text = proposal.get("reply_text") or ""
    if len(reply_text) > 280:
        reply_text = reply_text[:277] + "..."
    joke_preview = proposal.get("joke_preview") or "<no preview>"
    fence = _markdown_fence_for(reply_text, joke_preview)

    lines = [
        "## Reported joke denylist proposal",
        "",
        "This PR was auto-generated from a user reply containing `#report`.",
        "",
        "### Evidence",
        f"- Joke hash: `{joke_hash}`",
        f"- Source post URI: `{proposal.get('source_post_uri')}`",
        f"- Report reply URI: `{proposal.get('source_reply_uri')}`",
        f"- Reporter DID: `{proposal.get('reporter_did')}`",
        "",
        "### Reply text",
        f"{fence}text",
        reply_text,
        fence,
        "",
        "### Joke preview",
        f"{fence}text",
        joke_preview,
        fence,
    ]
    return "\n".join(lines)


def _stage_jokebook_change(b64_value: str, joke_hash: str) -> bool:
    jokebook = load_jokebook(JOKEBOOK_PATH)
    if not remove_jokebook_entry(jokebook, b64_value):
        print(f"Skipping joke hash {joke_hash}; not found in jokebook")
        return False
    save_jokebook(jokebook, JOKEBOOK_PATH)
    run_command(["git", "add", str(JOKEBOOK_PATH)])
    return True


def _stage_denylist_change(proposal: dict, b64_value: str, joke_hash: str) -> bool:
    denylist = joke_denylist.load_denylist(DENYLIST_PATH)
    added = joke_denylist.add_denylist_entry(
        denylist,
        b64=b64_value,
        source_post_uri=proposal.get("source_post_uri") or "",
        source_reply_uri=proposal.get("source_reply_uri") or "",
        reporter_did=proposal.get("reporter_did") or "unknown",
        reason=proposal.get("reason") or "user_reply_report",
    )
    if not added:
        print(f"Skipping already denylisted joke hash {joke_hash}")
        return False
    joke_denylist.save_denylist(denylist, DENYLIST_PATH)
    run_command(["git", "add", str(DENYLIST_PATH)])
    return True


def create_pr_for_proposal(proposal: dict) -> str | None:
    b64_value = proposal.get("b64")
    if not b64_value:
        return None

    target = proposal_target(proposal)
    branch_name = branch_name_for_b64(b64_value, target)
    if find_review_pr(branch_name):
        print(f"Verified existing review PR for {branch_name}")
        return branch_name

    joke_hash = hashlib.sha1(b64_value.encode("utf-8")).hexdigest()[:8]
    if target == "jokebook":
        pr_title = f"chore(jokebook): remove reported joke {joke_hash}"
    else:
        pr_title = f"chore(denylist): add reported joke {joke_hash}"
    pr_body = build_pr_body(proposal, joke_hash)

    branch_created = False
    target_path = JOKEBOOK_PATH if target == "jokebook" else DENYLIST_PATH
    try:
        if has_remote_branch(branch_name):
            _verify_orphan_branch(branch_name, proposal, target_path)
        else:
            run_command(["git", "diff", "--exit-code", "HEAD", "--", str(target_path)])
            run_command(["git", "checkout", "-b", branch_name])
            branch_created = True
            staged = (
                _stage_jokebook_change(b64_value, joke_hash)
                if target == "jokebook"
                else _stage_denylist_change(proposal, b64_value, joke_hash)
            )
            if not staged:
                raise RuntimeError(
                    "Report change is already applied but no review PR was verified"
                )
            run_command(["git", "commit", "-m", pr_title])
            run_command(["git", "push", "-u", "origin", branch_name])
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", encoding="utf-8"
        ) as body_file:
            body_file.write(pr_body)
            body_file.flush()
            run_command(
                [
                    "gh",
                    "pr",
                    "create",
                    "--base",
                    "main",
                    "--head",
                    branch_name,
                    "--title",
                    pr_title,
                    "--body-file",
                    body_file.name,
                ]
            )
        if not find_review_pr(branch_name):
            raise RuntimeError("Report PR creation could not be verified")

        print(f"Created PR for {joke_hash}")
        return branch_name
    finally:
        if branch_created:
            try:
                run_command(
                    ["git", "restore", "--staged", "--worktree", "--", str(target_path)]
                )
                _cleanup_local_branch(branch_name)
            except subprocess.CalledProcessError as exc:
                raise BranchCleanupError(
                    "Could not restore main; stopping report delivery"
                ) from exc


def _verify_orphan_branch(branch_name, proposal, target_path):
    relative_path = target_path.relative_to(RESOURCES_DIR.parent).as_posix()
    run_command(["git", "fetch", "origin", branch_name])
    paths = run_command(
        ["git", "diff", "--name-only", "origin/main...FETCH_HEAD"]
    ).stdout.splitlines()
    if paths != [relative_path]:
        raise RuntimeError("Orphan report branch has unexpected changed files")
    base = run_command(
        ["git", "merge-base", "origin/main", "FETCH_HEAD"]
    ).stdout.strip()
    original = json.loads(
        run_command(["git", "show", f"{base}:{relative_path}"]).stdout
    )
    proposed = json.loads(
        run_command(["git", "show", f"FETCH_HEAD:{relative_path}"]).stdout
    )
    b64_value = proposal["b64"]
    if proposal_target(proposal) == "jokebook":
        expected = {
            **original,
            "jokes": [joke for joke in original["jokes"] if joke != b64_value],
        }
        valid = proposed == expected and proposed != original
    else:
        added = [entry for entry in proposed["jokes"] if entry not in original["jokes"]]
        valid = (
            len(added) == 1
            and added[0].get("b64") == b64_value
            and added[0].get("source_post_uri")
            == (proposal.get("source_post_uri") or "")
            and added[0].get("source_reply_uri")
            == (proposal.get("source_reply_uri") or "")
            and all(entry in proposed["jokes"] for entry in original["jokes"])
            and len(proposed["jokes"]) == len(original["jokes"]) + 1
            and {k: v for k, v in proposed.items() if k != "jokes"}
            == {k: v for k, v in original.items() if k != "jokes"}
        )
    if not valid:
        raise RuntimeError("Orphan report branch does not match the queued proposal")


def _with_fresh_evidence(queued, fresh):
    matches = all(
        queued.get(field) == fresh.get(field)
        for field in ("source_post_uri", "source_reply_uri")
    )
    if not matches:
        return dict(queued)
    return {**fresh, **queued}


def main() -> None:
    proposals_path = Path(
        os.getenv("BLUESKY_REPORT_OUTPUT", str(DEFAULT_PROPOSALS_PATH))
    )
    payload = json.loads(proposals_path.read_text()) if proposals_path.exists() else {}
    proposals = payload.get("proposals", [])
    state = bot_state.load_state()
    if proposals:
        report_transactions.enqueue_proposals(state, proposals)
    pending = dict(report_transactions.pending_proposals(state))
    fresh = {
        report_transactions.proposal_key(proposal): proposal
        for proposal in proposals
        if proposal.get("b64")
    }
    if not pending:
        print("No report proposals found; no PRs to create")
        return

    created_count = 0
    failures = 0
    for key, queued in pending.items():
        proposal = _with_fresh_evidence(queued, fresh.get(key, {}))
        try:
            branch = create_pr_for_proposal(proposal)
            proof = find_review_pr(branch) if branch else None
            if not proof:
                raise RuntimeError("Report proposal has no verified review PR")
            report_transactions.confirm_delivery(state, proposal, proof)
            created_count += 1
        except BranchCleanupError:
            raise
        except (subprocess.CalledProcessError, ValueError, RuntimeError) as exc:
            failures += 1
            print(f"Report delivery failed; proposal retained: {exc}", file=sys.stderr)

    print(f"Report deliveries verified: {created_count}; failed: {failures}.")
    if failures:
        raise RuntimeError(f"{failures} report proposal delivery attempt(s) failed")


if __name__ == "__main__":
    main()
