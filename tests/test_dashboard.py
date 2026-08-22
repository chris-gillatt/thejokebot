import json
import unittest
from datetime import datetime, timezone

import bluesky_collect_dashboard_metrics as dashboard


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _Session:
    def __init__(self, profile, latest_post, feed_pages):
        self.profile = profile
        self.latest_post = latest_post
        self.feed_pages = feed_pages

    def get(self, url, params, timeout):
        del timeout
        method = url.rsplit("/", 1)[-1]
        if method == "app.bsky.actor.getProfile":
            return _Response(self.profile)
        if method == "app.bsky.feed.getPosts":
            return _Response({"posts": [self.latest_post]})
        if method == "app.bsky.feed.getAuthorFeed":
            if params["includePins"] != "false":
                raise AssertionError("includePins must use the XRPC boolean format")
            return _Response(self.feed_pages[params.get("cursor")])
        raise AssertionError(f"Unexpected method: {method}")


def _post(uri, author="did:bot", text="A joke", **counts):
    return {
        "uri": uri,
        "author": {"did": author},
        "record": {"text": text, "createdAt": "2026-08-22T00:00:00Z"},
        "indexedAt": "2026-08-22T00:00:01Z",
        **counts,
    }


class DashboardCollectorTests(unittest.TestCase):
    def setUp(self):
        self.first_uri = "at://did:bot/app.bsky.feed.post/first"
        self.latest_uri = "at://did:bot/app.bsky.feed.post/latest"
        self.profile = {
            "did": "did:bot",
            "handle": "thejokebot.bsky.social",
            "displayName": "The Joke Bot",
            "followersCount": 6400,
            "followsCount": 10800,
            "postsCount": 2320,
        }
        self.latest_post = _post(
            self.latest_uri,
            text="The latest joke",
            likeCount=7,
            replyCount=2,
            repostCount=1,
            quoteCount=1,
            bookmarkCount=3,
        )
        self.state = {
            "posted_jokes": [
                {"ts": 1787350000, "post_uri": self.first_uri},
                {"ts": 1787357528, "post_uri": self.latest_uri},
            ],
            "reports": {"deleted_post_uris": []},
            "unfollow_history": {
                "entries": [{"did": "did:audience", "unfollowed_at": 1787357000}]
            },
        }

    def test_collects_aggregates_without_audience_identifiers(self):
        first_post = _post(self.first_uri, likeCount=2, replyCount=1)
        repost = {"reason": {"by": "did:audience"}, "post": self.latest_post}
        reply = _post("at://did:bot/app.bsky.feed.post/reply")
        reply["record"]["reply"] = {"root": {}}
        audience_post = _post(
            "at://did:audience/app.bsky.feed.post/other", author="did:audience"
        )
        session = _Session(
            self.profile,
            self.latest_post,
            {
                None: {
                    "feed": [
                        {"post": first_post},
                        repost,
                        {"post": reply},
                        {"post": audience_post},
                    ],
                    "cursor": "next",
                },
                "next": {"feed": [{"post": self.latest_post}]},
            },
        )
        existing = {
            "schema_version": 1,
            "snapshots": [
                {
                    "period_start": "2026-08-22T00:00:00+00:00",
                    "collected_at": "2026-08-22T00:05:00+00:00",
                    "followers": 1,
                    "following": 1,
                    "profile_posts": 1,
                }
            ],
        }

        metrics = dashboard.collect_metrics(
            "thejokebot.bsky.social",
            self.state,
            existing=existing,
            session=session,
            now=datetime(2026, 8, 22, 2, 30, tzinfo=timezone.utc),
        )

        self.assertEqual(metrics["current"]["joke_posts"], 2)
        self.assertEqual(metrics["current"]["engagement"]["likes"], 9)
        self.assertEqual(metrics["current"]["engagement"]["bookmarks"], 3)
        self.assertEqual(metrics["latest_joke"]["uri"], self.latest_uri)
        self.assertEqual(len(metrics["snapshots"]), 1)
        self.assertEqual(metrics["snapshots"][0]["followers"], 6400)
        self.assertNotIn("did:audience", json.dumps(metrics))

    def test_latest_joke_skips_deleted_post(self):
        self.state["reports"]["deleted_post_uris"] = [self.latest_uri]
        self.assertEqual(dashboard._latest_joke_uri(self.state), self.first_uri)

    def test_repeated_feed_cursor_fails_closed(self):
        session = _Session(
            self.profile,
            self.latest_post,
            {
                None: {"feed": [], "cursor": "stalled"},
                "stalled": {"feed": [], "cursor": "stalled"},
            },
        )
        with self.assertRaisesRegex(RuntimeError, "repeated cursor"):
            dashboard.fetch_original_posts(session, "did:bot")

    def test_rejects_unknown_schema_version(self):
        with self.assertRaisesRegex(ValueError, "schema version"):
            dashboard._normalise_existing({"schema_version": 2, "snapshots": []})


if __name__ == "__main__":
    unittest.main()
