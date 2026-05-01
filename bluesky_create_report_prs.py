"""Create one denylist pull request per reported joke proposal."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import bluesky_denylist

DEFAULT_PROPOSALS_PATH = Path(".agent-tmp/report_proposals.json")
DENYLIST_PATH = Path("resources/jokebot_denylist.json")
JOKEBOOK_PATH = Path("resources/jokebot_jokebook.json")
JOKEBOOK_PROVIDER_NAME = "jokebot_jokebook"


def run_command(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, check=False, text=True, capture_output=True)
    if check and result.returncode != 0:
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        result.check_returncode()
    return result


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

    target = proposal_target(proposal)
    branch_name = branch_name_for_b64(b64_value, target)
    if has_remote_branch(branch_name) or has_open_pr_for_branch(branch_name):
        print(f"Skipping existing branch/PR for {branch_name}")
        return False

    joke_hash = hashlib.sha1(b64_value.encode("utf-8")).hexdigest()[:8]
    if target == "jokebook":
        pr_title = f"chore(jokebook): remove reported joke {joke_hash}"
    else:
        pr_title = f"chore(denylist): add reported joke {joke_hash}"
    pr_body = build_pr_body(proposal, joke_hash)

    run_command(["git", "checkout", "-b", branch_name])

    if target == "jokebook":
        jokebook = load_jokebook(JOKEBOOK_PATH)
        removed = remove_jokebook_entry(jokebook, b64_value)
        if not removed:
            run_command(["git", "checkout", "main"])
            run_command(["git", "branch", "-D", branch_name], check=False)
            print(f"Skipping joke hash {joke_hash}; not found in jokebook")
            return False
        save_jokebook(jokebook, JOKEBOOK_PATH)
        run_command(["git", "add", str(JOKEBOOK_PATH)])
    else:
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
