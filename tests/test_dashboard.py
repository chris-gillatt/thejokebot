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


class _WorkflowSession:
    def __init__(self, pages):
        self.pages = pages
        self.requested_pages = []

    def get(self, url, params, headers, timeout):
        del url, headers, timeout
        page = params["page"]
        self.requested_pages.append(page)
        return _Response({"workflow_runs": self.pages[page]})


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
                {
                    "ts": 1787350000,
                    "post_uri": self.first_uri,
                    "provider": "icanhazdadjoke",
                },
                {
                    "ts": 1787357528,
                    "post_uri": self.latest_uri,
                    "provider": "groandeck",
                },
            ],
            "provider": {
                "failures": {
                    "icanhazdadjoke": {
                        "count": 4,
                        "last_failure_at": 1787350000,
                        "last_error": "duplicate or too long",
                    }
                },
                "health_checks": {
                    "icanhazdadjoke": {
                        "last_check_at": 1787350000,
                        "last_check_success": True,
                        "consecutive_failures": 0,
                        "configured": True,
                    }
                },
            },
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
        providers = {item["name"]: item for item in metrics["providers"]["providers"]}
        self.assertEqual(providers["icanhazdadjoke"]["published"], 1)
        self.assertEqual(providers["icanhazdadjoke"]["fallthroughs"], 4)
        self.assertTrue(providers["icanhazdadjoke"]["configured"])
        self.assertEqual(providers["groandeck"]["average_interactions"], 14.0)
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
            dashboard._normalise_existing({"schema_version": 3, "snapshots": []})

    def test_normalise_existing_upgrades_schema_one(self):
        existing = {"schema_version": 1, "snapshots": []}
        self.assertEqual(
            dashboard._normalise_existing(existing)["schema_version"],
            dashboard.SCHEMA_VERSION,
        )

    def test_workflow_metrics_summarise_rolling_runs(self):
        now = datetime(2026, 8, 22, 6, tzinfo=timezone.utc)
        runs = [
            {
                "name": "python_tests",
                "conclusion": "success",
                "created_at": "2026-08-22T05:00:00Z",
            },
            {
                "name": "python_tests",
                "conclusion": "failure",
                "created_at": "2026-08-21T05:00:00Z",
            },
            {
                "name": "bluesky_post_joke",
                "conclusion": "success",
                "created_at": "2026-08-22T04:00:00Z",
            },
        ]

        summary = dashboard._workflow_metrics(runs, now)

        self.assertEqual(summary["runs"], 3)
        self.assertEqual(summary["successful"], 2)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["success_rate"], 66.7)
        tests = next(
            item for item in summary["workflows"] if item["name"] == "python_tests"
        )
        self.assertEqual(tests["last_conclusion"], "success")
        starter_pack = next(
            item
            for item in summary["workflows"]
            if item["name"] == "bluesky_manage_starter_pack"
        )
        self.assertEqual(starter_pack["runs"], 0)
        self.assertIsNone(starter_pack["last_conclusion"])

    def test_fetch_workflow_runs_collects_multiple_pages(self):
        runs = [
            {
                "name": "python_tests",
                "conclusion": "success",
                "created_at": "2026-08-22T05:00:00Z",
            }
            for _ in range(101)
        ]
        session = _WorkflowSession({1: runs[:100], 2: runs[100:]})

        collected = dashboard.fetch_workflow_runs(
            session,
            "owner/repository",
            "token",
            datetime(2026, 8, 22, 6, tzinfo=timezone.utc),
        )

        self.assertEqual(len(collected), 101)
        self.assertEqual(session.requested_pages, [1, 2])


if __name__ == "__main__":
    unittest.main()
