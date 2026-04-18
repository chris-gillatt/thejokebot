import argparse
import datetime as dt
import sys
from typing import Optional

from bluesky_common import login_client

DEFAULT_HASHTAGS = ("#jokes", "#dadjoke", "#funny")


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Read-only check: verify that at least one recent post on the configured "
            "account looks like a joke post (hashtags present)."
        )
    )
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=24.0,
        help="Maximum age of a matching post in hours (default: 24).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="How many recent feed items to inspect (default: 25).",
    )
    return parser.parse_args()


def parse_created_at(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def extract_text(feed_item) -> str:
    try:
        return str(feed_item.post.record.text)
    except Exception:
        return ""


def has_required_hashtags(text: str) -> bool:
    lowered = text.lower()
    return all(tag in lowered for tag in DEFAULT_HASHTAGS)


def to_post_url(handle: str, uri: str) -> Optional[str]:
    if not uri:
        return None
    parts = uri.split("/")
    if len(parts) < 1:
        return None
    rkey = parts[-1]
    if not rkey:
        return None
    return f"https://bsky.app/profile/{handle}/post/{rkey}"


def main() -> int:
    args = parse_args()

    client, username = login_client()
    did = client.me.did

    print(f"Checking recent posts for {username} ({did})...")

    feed = client.get_author_feed(actor=did, limit=args.limit)
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(hours=args.max_age_hours)

    newest_match = None

    for item in feed.feed:
        try:
            if item.post.author.did != did:
                continue
        except Exception:
            continue

        text = extract_text(item)
        if not text or not has_required_hashtags(text):
            continue

        created_at = parse_created_at(getattr(item.post.record, "created_at", None))
        if not created_at:
            continue

        if created_at >= cutoff:
            newest_match = (created_at, text, getattr(item.post, "uri", ""))
            break

    if not newest_match:
        print(
            f"FAIL: No matching joke post found in the last {args.max_age_hours} hours."
        )
        return 1

    created_at, text, uri = newest_match
    print("PASS: Found a recent joke post.")
    print(f"Created at: {created_at.isoformat()}")
    preview = text.replace("\n", " ")
    if len(preview) > 180:
        preview = preview[:177] + "..."
    print(f"Preview: {preview}")

    post_url = to_post_url(username, uri)
    if post_url:
        print(f"Post URL: {post_url}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
