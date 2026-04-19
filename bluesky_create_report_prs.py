"""Create one denylist pull request per reported joke proposal."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import bluesky_denylist

DEFAULT_PROPOSALS_PATH = Path(".agent-tmp/report_proposals.json")
DENYLIST_PATH = Path("resources/jokebot_denylist.json")


def run_command(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=check, text=True, capture_output=True)


def has_remote_branch(branch_name: str) -> bool:
    result = run_command(["git", "ls-remote", "--heads", "origin", branch_name], check=False)
    return bool(result.stdout.strip())


def has_open_pr_for_branch(branch_name: str) -> bool:
    result = run_command(
        [
            "gh",
            "pr",
            "list",
            "--head",
            branch_name,
            "--state",
            "open",
            "--json",
            "number",
        ],
        check=False,
    )
    if result.returncode != 0:
        return False
    try:
        rows = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return False
    return bool(rows)


def branch_name_for_b64(b64_value: str) -> str:
    suffix = hashlib.sha1(b64_value.encode("utf-8")).hexdigest()[:12]
    return f"chore/report-denylist-{suffix}"


def build_pr_body(proposal: dict, joke_hash: str) -> str:
    reply_text = proposal.get("reply_text") or ""
    if len(reply_text) > 280:
        reply_text = reply_text[:277] + "..."

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
        "```text",
        reply_text,
        "```",
        "",
        "### Joke preview",
        "```text",
        proposal.get("joke_preview") or "<no preview>",
        "```",
    ]
    return "\n".join(lines)


def create_pr_for_proposal(proposal: dict) -> bool:
    b64_value = proposal.get("b64")
    if not b64_value:
        return False

    branch_name = branch_name_for_b64(b64_value)
    if has_remote_branch(branch_name) or has_open_pr_for_branch(branch_name):
        print(f"Skipping existing branch/PR for {branch_name}")
        return False

    joke_hash = hashlib.sha1(b64_value.encode("utf-8")).hexdigest()[:8]
    pr_title = f"chore(denylist): add reported joke {joke_hash}"
    pr_body = build_pr_body(proposal, joke_hash)

    run_command(["git", "checkout", "-b", branch_name])

    denylist = bluesky_denylist.load_denylist(DENYLIST_PATH)
    added = bluesky_denylist.add_denylist_entry(
        denylist,
        b64=b64_value,
        source_post_uri=proposal.get("source_post_uri") or "",
        source_reply_uri=proposal.get("source_reply_uri") or "",
        reporter_did=proposal.get("reporter_did") or "unknown",
        reason=proposal.get("reason") or "user_reply_report",
    )
    if not added:
        run_command(["git", "checkout", "main"])
        run_command(["git", "branch", "-D", branch_name], check=False)
        print(f"Skipping already denylisted joke hash {joke_hash}")
        return False

    bluesky_denylist.save_denylist(denylist, DENYLIST_PATH)

    run_command(["git", "add", str(DENYLIST_PATH)])
    run_command(["git", "commit", "-m", pr_title])
    run_command(["git", "push", "-u", "origin", branch_name])
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
            "--body",
            pr_body,
        ]
    )

    run_command(["git", "checkout", "main"])
    run_command(["git", "branch", "-D", branch_name], check=False)
    print(f"Created PR for {joke_hash}")
    return True


def main() -> None:
    proposals_path = Path(os.getenv("BLUESKY_REPORT_OUTPUT", str(DEFAULT_PROPOSALS_PATH)))
    if not proposals_path.exists():
        print(f"No proposals file found at {proposals_path}; skipping PR creation")
        return

    with open(proposals_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    proposals = payload.get("proposals", [])
    if not proposals:
        print("No report proposals found; no PRs to create")
        return

    created_count = 0
    for proposal in proposals:
        if create_pr_for_proposal(proposal):
            created_count += 1

    print(f"Report proposals processed: {len(proposals)}")
    print(f"PRs created: {created_count}")


if __name__ == "__main__":
    main()
