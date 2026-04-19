"""Process Bluesky #report replies and emit denylist PR proposals."""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

import requests

import bluesky_denylist
import bluesky_state
from atproto import models
from bluesky_common import login_client

REPORT_TAG_PATTERN = re.compile(r"(?:^|\s)#report\b", re.IGNORECASE)
TRAILING_TAGS_PATTERN = re.compile(r"\n\n(?:#\w+\s*)+$", re.IGNORECASE)
DEFAULT_OUTPUT_PATH = Path(".agent-tmp/report_proposals.json")
DEFAULT_MAX_PAGES = 3
DEFAULT_PAGE_LIMIT = 100

_ACK_TEXT = "Eek! Thanks for flagging that \U0001f648 I'll get it sent for review!"


def _get_value(data, *path):
    """Safely read nested values from dict or model-like objects."""
    cur = data
    for key in path:
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            cur = getattr(cur, key, None)
    return cur


def _normalise_text(record) -> str:
    text = _get_value(record, "text")
    if isinstance(text, str):
        return text
    return ""


def has_report_tag(text: str) -> bool:
    """Return True when text contains #report as a standalone hashtag."""
    return bool(REPORT_TAG_PATTERN.search(text or ""))


def _extract_parent_uri(notification) -> str | None:
    reason_subject = _get_value(notification, "reason_subject")
    if not reason_subject:
        reason_subject = _get_value(notification, "reasonSubject")
    if reason_subject:
        return reason_subject

    record = _get_value(notification, "record")
    return _get_value(record, "reply", "parent", "uri")


def _extract_notification(notification) -> dict:
    """Extract report-relevant fields from a notification payload."""
    record = _get_value(notification, "record")
    return {
        "reason": _get_value(notification, "reason"),
        "notification_uri": _get_value(notification, "uri"),
        "author_did": _get_value(notification, "author", "did") or "unknown",
        "reply_uri": _get_value(notification, "uri"),
        "reply_cid": _get_value(notification, "cid"),
        "reply_text": _normalise_text(record),
        "source_post_uri": _extract_parent_uri(notification),
        "root_uri": _get_value(notification, "record", "reply", "root", "uri"),
        "root_cid": _get_value(notification, "record", "reply", "root", "cid"),
        "indexed_at": _get_value(notification, "indexed_at") or _get_value(notification, "indexedAt"),
    }


def _decode_joke_preview(b64_text: str, max_chars: int = 180) -> str:
    try:
        decoded = base64.b64decode(b64_text).decode("utf-8", errors="replace")
    except Exception:
        return "<unable to decode joke text>"
    if len(decoded) <= max_chars:
        return decoded
    return decoded[: max_chars - 3] + "..."


def _extract_thread_post_text(client, post_uri: str) -> str | None:
    """Fetch the replied-to post text for fallback joke mapping."""
    try:
        response = client.get_post_thread(uri=post_uri, depth=0)
    except Exception:
        return None

    thread = _get_value(response, "thread")
    post = _get_value(thread, "post")
    record = _get_value(post, "record")
    text = _normalise_text(record)
    if not text:
        return None

    # Posted jokes append hashtags on a new paragraph. Strip trailing hashtags
    # so encoded text matches the stored joke body.
    text = TRAILING_TAGS_PATTERN.sub("", text).strip()
    return text or None


def _encode_text_b64(text: str | None) -> str | None:
    if not text:
        return None
    return base64.b64encode(text.encode("utf-8")).decode("utf-8")


def _delete_post(client, post_uri: str) -> tuple[bool, bool]:
    """
    Delete a single Bluesky post by AT URI.
    
    Returns (success, should_retry):
    - (True, False): Post deleted successfully
    - (False, True): Transient error (network/timeout); will retry on next run
    - (False, False): Permanent error (invalid URI/format); will not retry
    """
    try:
        parts = post_uri.split("/")
        if len(parts) < 4:
            print(f"Warning: invalid post URI format, skipping: {post_uri}")
            return False, False
        repo = parts[2]
        rkey = parts[-1]
        client.app.bsky.feed.post.delete(repo=repo, rkey=rkey)
        return True, False
    except (requests.RequestException, TimeoutError) as exc:
        print(f"Warning: transient error deleting post {post_uri}, will retry: {exc}")
        return False, True
    except (ValueError, AttributeError) as exc:
        print(f"Warning: permanent error deleting post {post_uri}, skipping: {exc}")
        return False, False


def acknowledge_report(client, proposal: dict) -> tuple[bool, bool]:
    """
    Reply to a #report notification to acknowledge receipt to the reporter.
    
    Returns (success, should_retry):
    - (True, False): Acknowledgement sent successfully
    - (False, True): Transient error (network/timeout); will retry on next run
    - (False, False): Permanent error (missing fields/invalid refs); will not retry
    """
    reply_uri = proposal.get("source_reply_uri")
    reply_cid = proposal.get("reply_cid")
    root_uri = proposal.get("root_uri") or proposal.get("source_post_uri")
    root_cid = proposal.get("root_cid")

    if not reply_uri or not reply_cid or not root_uri or not root_cid:
        return False, False

    try:
        reply_ref = models.AppBskyFeedPost.ReplyRef(
            parent=models.ComAtprotoRepoStrongRef.Main(uri=reply_uri, cid=reply_cid),
            root=models.ComAtprotoRepoStrongRef.Main(uri=root_uri, cid=root_cid),
        )
        client.send_post(text=_ACK_TEXT, reply_to=reply_ref)
        return True, False
    except (requests.RequestException, TimeoutError) as exc:
        print(f"Warning: transient error acknowledging {reply_uri}, will retry: {exc}")
        return False, True
    except (ValueError, AttributeError) as exc:
        print(f"Warning: permanent error acknowledging {reply_uri}, skipping: {exc}")
        return False, False


def delete_approved_report_posts(client, denylist: dict, state: dict) -> int:
    """Delete original joke posts whose denylist entries have been approved.

    Iterates over denylist entries that carry a source_post_uri. Any URI not
    yet recorded as deleted in state is attempted. Successfully deleted URIs
    are recorded so the attempt is not retried. Permanent errors are marked to
    avoid retry spam; transient errors are left unrecorded for next attempt.

    Returns the number of posts deleted in this run.
    """
    already_deleted = bluesky_state.get_deleted_post_uris(state)
    deleted_count = 0

    for entry in denylist.get("jokes", []):
        uri = entry.get("source_post_uri")
        if not uri or uri in already_deleted:
            continue
        success, should_retry = _delete_post(client, uri)
        if success:
            bluesky_state.record_deleted_post_uri(state, uri)
            deleted_count += 1
            print(f"Deleted approved report post: {uri}")
        elif not should_retry:
            # Mark permanent failures to avoid retrying forever
            bluesky_state.record_deleted_post_uri(state, uri)
            print(f"Recorded permanent failure for: {uri}")

    return deleted_count


def collect_report_proposals(client, state: dict, denylisted_b64s: set[str]) -> tuple[list[dict], set[str], int]:
    """Collect new denylist proposals from reply notifications."""
    processed_uris = bluesky_state.get_processed_notification_uris(state)
    post_uri_index = bluesky_state.get_post_uri_index(state)

    page_limit = int(os.getenv("BLUESKY_REPORT_PAGE_LIMIT", str(DEFAULT_PAGE_LIMIT)))
    max_pages = int(os.getenv("BLUESKY_REPORT_MAX_PAGES", str(DEFAULT_MAX_PAGES)))

    cursor = None
    proposals: list[dict] = []
    seen_b64s: set[str] = set()
    processed_notifications: set[str] = set()

    pages_fetched = 0
    for _ in range(max_pages):
        response = client.app.bsky.notification.list_notifications(
            params={
                "cursor": cursor,
                "limit": page_limit,
                "reasons": ["reply"],
            }
        )
        pages_fetched += 1

        notifications = _get_value(response, "notifications") or []
        for notification in notifications:
            parsed = _extract_notification(notification)
            notification_uri = parsed["notification_uri"]
            if not notification_uri:
                continue
            if notification_uri in processed_uris:
                continue
            if parsed["reason"] != "reply":
                processed_notifications.add(notification_uri)
                continue
            if not has_report_tag(parsed["reply_text"]):
                processed_notifications.add(notification_uri)
                continue

            source_post_uri = parsed["source_post_uri"]
            if not source_post_uri:
                processed_notifications.add(notification_uri)
                continue
            posted_entry = post_uri_index.get(source_post_uri)
            b64_value = posted_entry.get("b64") if posted_entry else None
            if not b64_value:
                fetched_text = _extract_thread_post_text(client, source_post_uri)
                b64_value = _encode_text_b64(fetched_text)
            if not b64_value:
                # Keep this notification retriable in case of transient API issues.
                continue
            if not b64_value or b64_value in denylisted_b64s or b64_value in seen_b64s:
                processed_notifications.add(notification_uri)
                continue

            proposal = {
                "b64": b64_value,
                "source_post_uri": source_post_uri,
                "source_reply_uri": parsed["reply_uri"],
                "reply_cid": parsed["reply_cid"],
                "root_uri": parsed["root_uri"] or source_post_uri,
                "root_cid": parsed["root_cid"],
                "reporter_did": parsed["author_did"],
                "reply_text": parsed["reply_text"],
                "reply_indexed_at": parsed["indexed_at"],
                "joke_preview": _decode_joke_preview(b64_value),
                "reason": "user_reply_report",
            }
            proposals.append(proposal)
            seen_b64s.add(b64_value)
            processed_notifications.add(notification_uri)

        cursor = _get_value(response, "cursor")
        if not cursor:
            break

    return proposals, processed_notifications, pages_fetched


def _write_output(output_path: Path, payload: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def main() -> None:
    output_path = Path(os.getenv("BLUESKY_REPORT_OUTPUT", str(DEFAULT_OUTPUT_PATH)))

    state = bluesky_state.load_state()
    denylist = bluesky_denylist.load_denylist()
    denylisted_b64s = bluesky_denylist.get_denylisted_b64s(denylist)

    client, _ = login_client()

    deleted_count = delete_approved_report_posts(client, denylist, state)

    proposals, processed_notifications, pages_fetched = collect_report_proposals(
        client,
        state,
        denylisted_b64s,
    )

    for notification_uri in processed_notifications:
        bluesky_state.record_processed_notification(state, notification_uri)
    bluesky_state.prune_processed_notifications(state)
    bluesky_state.set_reports_checked_now(state)

    acknowledged_uris = bluesky_state.get_acknowledged_report_uris(state)
    ack_count = 0
    for proposal in proposals:
        reply_uri = proposal.get("source_reply_uri")
        if reply_uri and reply_uri not in acknowledged_uris:
            success, should_retry = acknowledge_report(client, proposal)
            if success:
                bluesky_state.record_acknowledged_report_uri(state, reply_uri)
                ack_count += 1
                print(f"Acknowledged report reply: {reply_uri}")
            elif not should_retry:
                # Mark permanent failures to avoid retrying forever
                bluesky_state.record_acknowledged_report_uri(state, reply_uri)
                print(f"Recorded permanent failure for: {reply_uri}")

    bluesky_state.save_state(state)

    payload = {
        "source": "app.bsky.notification.listNotifications",
        "pages_fetched": pages_fetched,
        "proposal_count": len(proposals),
        "proposals": proposals,
    }
    _write_output(output_path, payload)

    print(f"Processed notifications: {len(processed_notifications)}")
    print(f"New report proposals: {len(proposals)}")
    print(f"Report replies acknowledged: {ack_count}")
    print(f"Approved posts deleted: {deleted_count}")
    print(f"Output written to {output_path}")


if __name__ == "__main__":
    main()
