"""Deliver repost reviews and handle authorised GitHub issue decisions."""

import argparse
import copy
import html
import json
import os
import re
import subprocess
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

from thejokebot import repost_reviews as reviews
from thejokebot import state as bot_state
from thejokebot import state_transactions
from thejokebot.commands import dashboard_reposts
from thejokebot.paths import AGENT_TMP_DIR
from thejokebot.runtime import (
    get_nested_value,
    get_runtime_controls,
    login_client,
    retry_network_call,
)

REPOSITORY = "chris-gillatt/thejokebot"
REPOSITORY_ID = 901122902
ACTIONS_BOT_ID = 41898282
REPORT_PREFIX = "[Repost report]"
TERMINAL_STATUSES = {
    "published",
    "already_reposted",
    "rejected",
    "expired",
    "removed",
    "already_removed",
}


def github_api(path: str, method: str = "GET", payload: dict | None = None) -> dict:
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                "--method",
                method,
                *(["--input", "-"] if payload else []),
                "--",
                path,
            ],
            input=json.dumps(payload) if payload else None,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"GitHub repost review request failed: {exc.stderr}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "GitHub repost review request timed out; verify its outcome before retrying"
        ) from exc
    response = json.loads(result.stdout)
    if not isinstance(response, dict):
        raise ValueError("Unexpected GitHub repost review response")
    return response


def post_url(post: dict) -> str:
    match = reviews.POST_URI.fullmatch(post["uri"])
    if match is None:
        raise ValueError("Invalid reviewed post URI")
    return f"https://bsky.app/profile/{quote(match.group(1), safe=':')}/post/{quote(match.group(2), safe='')}"


def review_title(candidate: dict) -> str:
    return f"[Repost review] {candidate['key']}"


def _post_markdown(post: dict) -> list[str]:
    lines = [f"[View original post and thread]({post_url(post)})", ""]
    lines.extend("    " + line for line in post["text"].splitlines())
    if not post["text"]:
        lines.append("_No post text; inspect the original and any images._")
    for image in post["images"]:
        parsed = urlsplit(image["url"])
        if parsed.scheme != "https" or parsed.netloc != "cdn.bsky.app":
            raise ValueError("Unexpected review image origin")
        lines.extend(["", f"![Original post image]({image['url']})"])
    return lines


def review_body(candidate: dict) -> str:
    action = (
        "Remove TJB's repost"
        if candidate["action"] == "remove"
        else "Repost under TJB's account"
    )
    lines = [
        f"## {action}",
        "",
        f"Author: `@{candidate['post']['handle'] or 'unavailable'}`",
        "",
        (
            "An authorised maintainer can close this issue as **completed** to approve, "
            "or **not planned** to reject. Closure is approval, not proof of publication "
            "or removal; wait for the bot's confirmation comment."
        ),
        "",
        f"Review expires: `{candidate['expires_at']}`.",
        "",
        f"Approved content CID: `{candidate['post']['cid']}`.",
        "",
        *_post_markdown(candidate["post"]),
    ]
    for parent in candidate["context"]:
        lines.extend(["", "### Thread context", "", *_post_markdown(parent)])
    lines.extend(
        [
            "",
            f"Review key: `{candidate['key']}`.",
            "",
            "To flag a published repost, use the "
            f"[repost report form](https://github.com/{REPOSITORY}/issues/new?template=repost_report.yml). "
            "Replying to another author's original does not reliably notify TJB.",
        ]
    )
    return "\n".join(lines)


def _bind_issue(state: dict, candidate: dict, issue: dict) -> None:
    if (
        issue.get("title") != review_title(candidate)
        or issue.get("body") != review_body(candidate)
        or issue.get("user", {}).get("id") != ACTIONS_BOT_ID
        or not isinstance(issue.get("id"), int)
        or not isinstance(issue.get("number"), int)
    ):
        raise ValueError("Existing GitHub review does not match the saved proposal")
    ready = reviews.timestamp(issue["created_at"]).isoformat()
    reviews.update_review(
        state,
        candidate["key"],
        issue_id=issue["id"],
        issue_number=issue["number"],
        review_ready_at=ready,
    )


def deliver_reviews(state: dict, now=None) -> None:
    reviews.require_live()
    delivered = 0
    for candidate in list(state["repost_reviews"]["candidates"].values()):
        if (
            candidate["status"] != "proposed"
            or candidate.get("issue_id")
            or candidate["action"] != "repost"
        ):
            continue
        if reviews.timestamp(candidate["expires_at"]) <= reviews.utc_now(now):
            reviews.update_review(state, candidate["key"], status="expired")
            continue
        if delivered >= reviews.MAX_CANDIDATES:
            break
        query = urlencode(
            {
                "q": f"repo:{REPOSITORY} is:issue in:title {candidate['key']}",
                "per_page": 10,
            }
        )
        found = github_api(f"/search/issues?{query}")
        if found.get("incomplete_results") or found.get("total_count") not in (0, 1):
            raise ValueError("Could not uniquely resolve the GitHub repost review")
        if found["total_count"]:
            number = found["items"][0]["number"]
            issue = github_api(f"/repos/{REPOSITORY}/issues/{number}")
        else:
            if candidate.get("delivery_attempted"):
                raise ValueError(
                    "Previous review creation is uncertain; verify GitHub before retrying"
                )
            reviews.update_review(state, candidate["key"], delivery_attempted=True)
            issue = github_api(
                f"/repos/{REPOSITORY}/issues",
                "POST",
                {
                    "title": review_title(candidate),
                    "body": review_body(candidate),
                    "assignees": [REPOSITORY.split("/")[0]],
                },
            )
        _bind_issue(state, candidate, issue)
        delivered += 1
    print(f"Repost review delivery: {delivered} proposals delivered or recovered.")


def expire_reviews(state: dict, now=None) -> None:
    reviews.require_live()
    for candidate in list(state["repost_reviews"]["candidates"].values()):
        if (
            candidate["status"] in TERMINAL_STATUSES
            or candidate["status"] in reviews.UNCERTAIN_STATUSES
        ):
            continue
        if reviews.timestamp(candidate["expires_at"]) > reviews.utc_now(now):
            continue
        if candidate.get("issue_number"):
            github_api(
                f"/repos/{REPOSITORY}/issues/{candidate['issue_number']}",
                "PATCH",
                {
                    "state": "closed",
                    "state_reason": "not_planned",
                },
            )
        reviews.update_review(state, candidate["key"], status="expired")
        print("Expired a repost review without an account action.")


def _validate_event(event: dict) -> int:
    repository = event.get("repository", {})
    if (
        repository.get("id") != REPOSITORY_ID
        or repository.get("full_name") != REPOSITORY
    ):
        raise ValueError("Repost review event belongs to another repository")
    number = event.get("issue", {}).get("number")
    if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        raise ValueError("Repost review event needs a positive integer issue number")
    return int(number)


def _authorise(event: dict, issue: dict, candidate: dict) -> None:
    actor = event["sender"]
    if (
        actor.get("type") != "User"
        or issue.get("state") != "closed"
        or issue.get("closed_by", {}).get("id") != actor.get("id")
        or issue.get("updated_at") != event["issue"].get("updated_at")
        or reviews.timestamp(issue["closed_at"])
        < reviews.timestamp(candidate["review_ready_at"])
    ):
        raise ValueError("Stale, premature or unauthorised repost review decision")
    permission = github_api(
        f"/repos/{REPOSITORY}/collaborators/{quote(actor['login'], safe='')}/permission"
    )
    if permission.get("user", {}).get("id") != actor.get("id") or permission.get(
        "permission"
    ) not in ("admin", "maintain", "write"):
        raise ValueError("Repost approval requires a verified repository maintainer")


def _report_uri(client, body: str) -> str:
    field = re.search(r"(?m)^### Original Bluesky post[ \t]*\r?$", body)
    if field is None:
        raise ValueError("Repost report has no original post field")
    following = body[field.end() :].split(maxsplit=1)
    if not following:
        raise ValueError("Repost report has no original post value")
    value = following[0]
    if reviews.POST_URI.fullmatch(value):
        return value
    parsed = urlsplit(value)
    match = re.fullmatch(r"/profile/([^/]+)/post/([A-Za-z0-9._~:-]+)", parsed.path)
    if parsed.scheme != "https" or parsed.netloc != "bsky.app" or match is None:
        raise ValueError("Repost report needs a canonical Bluesky post link or AT URI")
    actor, key = match.groups()
    if not actor.startswith("did:"):
        if not reviews.HANDLE.fullmatch(actor):
            raise ValueError("Invalid reported author handle")
        response = retry_network_call(
            lambda: client.com.atproto.identity.resolve_handle({"handle": actor}),
            description="resolving a reported repost author",
        )
        actor = get_nested_value(response, "did")
    uri = f"at://{actor}/app.bsky.feed.post/{key}"
    if not reviews.POST_URI.fullmatch(uri):
        raise ValueError("Reported author did not resolve to a canonical DID")
    return uri


def _prepare_report(client, state: dict, issue: dict, now=None) -> None:
    key = f"report-{issue['id']}"
    if key in state["repost_reviews"]["candidates"]:
        print("Repost report is already queued.")
        return
    now = reviews.utc_now(now)
    uri = _report_uri(client, issue["body"])
    inventory = reviews.read_inventory(client, now)
    entry = next(
        (entry for entry in inventory["entries"] if entry["post_uri"] == uri), None
    )
    if entry is None:
        raise ValueError("Reported post is not in TJB's current repost inventory")
    post = {
        "uri": uri,
        "cid": entry["subject_cid"],
        "author_did": entry["author_did"],
        "handle": entry["handle"],
        "text": "",
        "images": [],
        "kind": entry["kind"],
        "is_reply": entry["is_reply"],
    }
    originals = reviews._posts(
        client, [uri], time.monotonic() + reviews.MAX_RUNTIME_SECONDS
    )
    original = originals.get(uri)
    if original is not None and original.get("cid") == entry["subject_cid"]:
        post = reviews.preview_post(original)
    else:
        print(
            "Reported original is unavailable or changed; retaining the exact repost record for removal review."
        )
    candidate = {
        "key": key,
        "action": "remove",
        "post": post,
        "context": [],
        "queued_at": now.isoformat(),
        "expires_at": (now + timedelta(days=reviews.REVIEW_EXPIRY_DAYS)).isoformat(),
        "status": "proposed",
        "issue_id": issue["id"],
        "issue_number": issue["number"],
        "repost_uri": entry["repost_uri"],
        "repost_cid": entry["repost_cid"],
    }
    comment = github_api(
        f"/repos/{REPOSITORY}/issues/{issue['number']}/comments",
        "POST",
        {
            "body": review_body(candidate),
        },
    )
    candidate["review_ready_at"] = reviews.timestamp(comment["created_at"]).isoformat()

    def record(latest):
        latest["repost_reviews"]["candidates"].setdefault(key, copy.deepcopy(candidate))

    state_transactions.apply(state, record)


def _confirmation(candidate: dict) -> str:
    outcomes = {
        "published": "Confirmed: reposted under TJB's account.",
        "removed": "Confirmed: removed TJB's repost, not the original author's post.",
        "already_reposted": "Already reposted; no new repost was created.",
        "already_removed": "The repost was already absent; no deletion was performed.",
        "rejected": "Review rejected; no account action was performed.",
    }
    return f"{outcomes[candidate['status']]}\n\n[Original post]({post_url(candidate['post'])})"


def _notify_outcome(state: dict, candidate: dict) -> None:
    if candidate.get("confirmation_comment_id"):
        print("Repost review outcome is already confirmed in GitHub.")
        return
    comment = github_api(
        f"/repos/{REPOSITORY}/issues/{candidate['issue_number']}/comments",
        "POST",
        {"body": _confirmation(candidate)},
    )
    if not isinstance(comment.get("id"), int):
        raise ValueError("GitHub did not confirm the repost outcome comment")
    reviews.update_review(
        state, candidate["key"], confirmation_comment_id=comment["id"]
    )


def handle_event(client, state: dict, event: dict, now=None) -> None:
    reviews.require_live()
    number = _validate_event(event)
    incoming = event["issue"]
    issue = github_api(f"/repos/{REPOSITORY}/issues/{number}")
    if issue.get("id") != incoming.get("id"):
        raise ValueError("GitHub issue identity does not match the review event")
    if event["action"] == "opened" and issue.get("title", "").startswith(REPORT_PREFIX):
        _prepare_report(client, state, issue, now)
        return
    if event["action"] != "closed":
        raise ValueError("Unsupported repost review event")
    candidate = next(
        (
            item
            for item in state["repost_reviews"]["candidates"].values()
            if item.get("issue_id") == issue["id"]
            and item.get("issue_number") == issue["number"]
        ),
        None,
    )
    if candidate is None:
        print("Closed issue is not a saved repost review; no action.")
        return
    _authorise(event, issue, candidate)
    if candidate["status"] == "expired":
        print("Repost review has expired; no repeated action.")
        return
    if candidate["status"] in TERMINAL_STATUSES:
        _notify_outcome(state, candidate)
        return
    if issue.get("state_reason") != "completed":
        if candidate["status"] in reviews.UNCERTAIN_STATUSES:
            raise ValueError(
                "Uncertain account action must be reconciled before changing the review decision"
            )
        candidate = reviews.update_review(state, candidate["key"], status="rejected")
    else:
        if candidate["status"] == "proposed":
            reviews.update_review(
                state,
                candidate["key"],
                status="approved",
                approved_at=issue["closed_at"],
                approver_id=event["sender"]["id"],
            )
        action = reviews.remove if candidate["action"] == "remove" else reviews.publish
        candidate = action(client, state, candidate["key"], now)
    _notify_outcome(state, candidate)


def _preview_post_html(post: dict) -> str:
    images = "".join(
        f'<img src="{html.escape(image["url"], quote=True)}" alt="{html.escape(image["alt"], quote=True)}">'
        for image in post["images"]
    )
    return (
        f"<section><h2>{html.escape(post['handle'])}</h2><pre>{html.escape(post['text'])}</pre>"
        f'{images}<p><a href="{post_url(post)}">Original post and thread</a></p></section>'
    )


def _write_preview(report: dict, state: dict, now) -> None:
    working = copy.deepcopy(state)
    working.setdefault("repost_reviews", {})["inventory"] = report["inventory"]
    payload = {**report, "metrics": dashboard_reposts.collect(working, now)}
    AGENT_TMP_DIR.mkdir(exist_ok=True)
    path = AGENT_TMP_DIR / "repost_preview.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    cards = []
    for candidate in report["candidates"]:
        context = "".join(
            "<h3>Thread context</h3>" + _preview_post_html(parent)
            for parent in candidate["context"]
        )
        cards.append(
            "<article>" + _preview_post_html(candidate["post"]) + context + "</article>"
        )
    (AGENT_TMP_DIR / "repost_preview.html").write_text(
        '<!doctype html><html lang="en-GB"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Read-only repost preview</title><style>body{font:1rem system-ui;max-width:60rem;margin:auto;padding:1rem}"
        "article{border:1px solid #ccc;padding:1rem;margin:1rem 0}img{max-width:100%;height:auto}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>Read-only repost preview</h1>"
        "<p>No review issues or account actions have been created.</p>"
        + "".join(cards)
        + "</html>\n",
        encoding="utf-8",
    )
    print(f"Read-only repost preview: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("preview", "inventory", "discover", "issue"),
        default="preview",
    )
    args = parser.parse_args()
    state = bot_state.load_state()
    if args.mode not in ("preview", "inventory"):
        reviews.require_live()
    if args.mode == "inventory" and get_runtime_controls()["dry_run"]:
        raise ValueError("Inventory checkpoints are disabled during a dry run")
    client, _ = login_client()
    if args.mode == "inventory":
        inventory = reviews.read_inventory(client)

        def record(latest):
            latest["repost_reviews"]["inventory"] = copy.deepcopy(inventory)

        state_transactions.apply(state, record)
        print(
            f"Repost inventory refreshed: {len(inventory['entries'])} retained subjects."
        )
        return
    if args.mode == "issue":
        event = json.loads(
            Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
        )
        handle_event(client, state, event)
        return
    now = reviews.utc_now()
    report = reviews.discover(client, state)
    if args.mode == "preview":
        _write_preview(report, state, now)
        return
    reviews.checkpoint_discovery(state, report)
    expire_reviews(state)
    deliver_reviews(state)


if __name__ == "__main__":
    main()
