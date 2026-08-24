import json
import io
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import bluesky_collect_dashboard_metrics as dashboard
import bluesky_follows_and_likes
import bluesky_post_joke
import bluesky_process_reports


class _Response:
    def __init__(self, payload=None, content=None):
        self.payload = payload
        self.content = content

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


class _LogSession:
    def __init__(self, content):
        self.content = content

    def get(self, url, headers, timeout):
        del url, headers, timeout
        return _Response(content=self.content)


def _log_archive(text):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("job.txt", text)
    return buffer.getvalue()


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
                        "reason_counts": {
                            "duplicate": 11,
                            "too_long": 2,
                            "network_error": 1,
                            "provider_error": 0,
                        },
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
        self.assertEqual(metrics["snapshots"][0]["engagement_total"], 17)
        self.assertEqual(
            metrics["engagement_momentum"]["deltas"], {"7": None, "30": None}
        )
        providers = {item["name"]: item for item in metrics["providers"]["providers"]}
        self.assertEqual(providers["icanhazdadjoke"]["published"], 1)
        self.assertEqual(providers["icanhazdadjoke"]["fallthroughs"], 4)
        self.assertEqual(
            providers["icanhazdadjoke"]["rejection_counts"],
            {
                "duplicate": 11,
                "too_long": 2,
                "network_error": 1,
                "provider_error": 0,
            },
        )
        self.assertTrue(providers["icanhazdadjoke"]["configured"])
        self.assertEqual(providers["groandeck"]["visible_posts"], 1)
        self.assertIsNone(providers["groandeck"]["average_interactions"])
        self.assertNotIn("did:audience", json.dumps(metrics))

    def test_provider_average_requires_minimum_visible_sample(self):
        uri_prefix = "at://did:bot/app.bsky.feed.post/"
        posts = [
            _post(f"{uri_prefix}{index}", likeCount=index)
            for index in range(dashboard.PROVIDER_COMPARISON_MIN_POSTS)
        ]
        state = {
            "posted_jokes": [
                {"post_uri": post["uri"], "provider": "sampled"} for post in posts
            ],
            "provider": {"failures": {}, "health_checks": {}},
        }

        below_minimum = dashboard._provider_metrics(state, posts[:-1])
        at_minimum = dashboard._provider_metrics(state, posts)

        self.assertIsNone(below_minimum["providers"][0]["average_interactions"])
        self.assertEqual(at_minimum["providers"][0]["average_interactions"], 14.5)
        self.assertEqual(
            at_minimum["minimum_comparison_posts"],
            dashboard.PROVIDER_COMPARISON_MIN_POSTS,
        )

    def test_latest_joke_skips_deleted_post(self):
        self.state["reports"]["deleted_post_uris"] = [self.latest_uri]
        self.assertEqual(dashboard._latest_joke_uri(self.state), self.first_uri)

    def test_top_posts_returns_six_highest_ranked_posts(self):
        posts = [
            _post(f"at://did:bot/app.bsky.feed.post/{index}", likeCount=index)
            for index in range(7)
        ]

        summaries = dashboard._top_post_summaries(posts, "thejokebot.bsky.social")

        self.assertEqual(len(summaries), 6)
        self.assertTrue(summaries[0]["uri"].endswith("/6"))
        self.assertTrue(summaries[-1]["uri"].endswith("/1"))

    def test_top_posts_by_window_ranks_only_posts_observed_in_each_period(self):
        now = datetime(2026, 8, 24, tzinfo=timezone.utc)
        recent = _post("at://did:bot/app.bsky.feed.post/recent", likeCount=2)
        recent["record"]["createdAt"] = "2026-08-23T00:00:00Z"
        monthly = _post("at://did:bot/app.bsky.feed.post/monthly", likeCount=5)
        monthly["record"]["createdAt"] = "2026-08-10T00:00:00Z"
        older = _post("at://did:bot/app.bsky.feed.post/older", likeCount=9)
        older["record"]["createdAt"] = "2026-07-01T00:00:00Z"

        windows = dashboard._top_posts_by_window(
            [recent, monthly, older], "thejokebot.bsky.social", now
        )

        self.assertEqual([post["uri"] for post in windows["7"]], [recent["uri"]])
        self.assertEqual(
            [post["uri"] for post in windows["30"]],
            [monthly["uri"], recent["uri"]],
        )
        self.assertEqual(
            [post["uri"] for post in windows["all"]],
            [older["uri"], monthly["uri"], recent["uri"]],
        )

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
            dashboard._normalise_existing({"schema_version": 8, "snapshots": []})

    def test_normalise_existing_upgrades_schema_one(self):
        existing = {"schema_version": 1, "snapshots": []}
        self.assertEqual(
            dashboard._normalise_existing(existing)["schema_version"],
            dashboard.SCHEMA_VERSION,
        )

    def test_parses_and_summarises_moderation_without_identifiers(self):
        line = bluesky_process_reports._moderation_summary_line(3, 2, 1, 4)

        counts = dashboard._workflow_activity_counts("bluesky_process_reports", line)
        activity = {
            "runs": [
                {
                    "workflow": "bluesky_process_reports",
                    "created_at": "2026-08-22T10:00:00Z",
                    **counts,
                }
            ]
        }
        summary = dashboard._moderation_metrics(activity)

        self.assertEqual(summary["proposals"], 3)
        self.assertEqual(summary["acknowledgements"], 2)
        self.assertEqual(summary["approved_removals"], 1)
        self.assertEqual(summary["unresolved"], 4)
        self.assertNotIn("uri", json.dumps(summary))

    def test_parses_and_summarises_provider_pressure_from_run_events(self):
        line = bluesky_post_joke._provider_summary_line(
            [("jokeapi", "duplicates", {"duplicate": 4, "too_long": 1})],
            "groandeck",
            True,
        )
        counts = dashboard._workflow_activity_counts("bluesky_post_joke", line)
        activity = {
            "runs": [
                {
                    "workflow": "bluesky_post_joke",
                    "created_at": "2026-08-22T10:00:00Z",
                    **counts,
                }
            ]
        }

        pressure = dashboard._provider_pressure_metrics(
            activity, datetime(2026, 8, 24, tzinfo=timezone.utc)
        )

        self.assertEqual(pressure["windows"]["7"]["completed_runs"], 1)
        self.assertEqual(pressure["windows"]["7"]["average_attempts"], 2.0)
        self.assertEqual(pressure["windows"]["7"]["fallthrough_rate"], 100.0)
        self.assertEqual(
            pressure["windows"]["7"]["rejections"],
            {
                "duplicate": 4,
                "too_long": 1,
                "network_error": 0,
                "provider_error": 0,
            },
        )
        self.assertEqual(
            pressure["windows"]["7"]["successful_sources"], {"groandeck": 1}
        )

    def test_engagement_momentum_requires_full_observed_windows(self):
        now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
        snapshots = [
            {
                "source": "bluesky_snapshot",
                "collected_at": "2026-08-01T12:00:00Z",
                "engagement_total": 100,
            },
            {
                "source": "bluesky_snapshot",
                "collected_at": "2026-08-24T12:00:00Z",
                "engagement_total": 130,
            },
            {
                "source": "bluesky_snapshot",
                "collected_at": now.isoformat(),
                "engagement_total": 145,
            },
        ]

        momentum = dashboard._engagement_momentum(snapshots, now)

        self.assertEqual(momentum["deltas"], {"7": 15, "30": 45})
        self.assertEqual(momentum["basis"], "visible_joke_snapshot_total")

    def test_parses_confirmed_follow_and_unfollow_counts(self):
        follows_and_likes = "\n".join(
            [
                "\x1b[32mFollowed did:...one\x1b[0m",
                "Followed interactor did:...two",
                "Followed 1 new interactor.",
            ]
        )
        discovery = "\n".join(
            [
                "Total users to follow: 8",
                "Unexpected error trying to follow did:...failed: timeout",
            ]
        )
        discovery_summary = (
            "Discovery summary: selected=8, followed=6, failed=2, dry_run=false."
        )
        social_summary = bluesky_follows_and_likes._social_summary_line(
            {
                "follow_back_candidates": 8,
                "follow_back_added": 5,
                "protected": 3,
                "interaction_candidates": 12,
                "interaction_eligible": 4,
                "interaction_added": 3,
                "interactions_liked": 7,
                "failed": 2,
            },
            dry_run=False,
        )

        self.assertEqual(
            dashboard._workflow_activity_counts(
                "bluesky_follows_and_likes", follows_and_likes
            ),
            {"follows": 2, "unfollows": 0},
        )
        self.assertEqual(
            dashboard._workflow_activity_counts(
                "bluesky_follows_and_likes", social_summary
            ),
            {
                "follows": 8,
                "unfollows": 0,
                "follow_back_candidates": 8,
                "follow_back_added": 5,
                "protected": 3,
                "interaction_candidates": 12,
                "interaction_eligible": 4,
                "interaction_added": 3,
                "interactions_liked": 7,
                "failed": 2,
            },
        )
        self.assertEqual(
            dashboard._workflow_activity_counts("bluesky_follow_fellows", discovery),
            {"follows": 7, "unfollows": 0, "selected": 8, "failed": 1},
        )
        self.assertEqual(
            dashboard._workflow_activity_counts(
                "bluesky_follow_fellows", discovery_summary
            ),
            {"follows": 6, "unfollows": 0, "selected": 8, "failed": 2},
        )
        self.assertEqual(
            dashboard._workflow_activity_counts(
                "bluesky_unfollow",
                "Found 9 users to unfollow (excluding ignorable accounts).\n"
                "Run stopped early after throttle detection.\n"
                "Summary: processed=5, unfollowed=4, failed=1, missing_uri=0.",
            ),
            {
                "follows": 0,
                "unfollows": 4,
                "eligible": 9,
                "processed": 5,
                "failed": 1,
                "missing_uri": 0,
                "stopped_early": True,
            },
        )
        self.assertEqual(
            dashboard._workflow_activity_counts(
                "bluesky_follow_fellows",
                "Dry-run mode enabled.\nTotal users to follow: 8",
            ),
            {"follows": 0, "unfollows": 0},
        )

    def test_fetch_workflow_run_logs_reads_zip_archive(self):
        logs = dashboard.fetch_workflow_run_logs(
            _LogSession(_log_archive("Followed did:...safe")),
            "owner/repository",
            123,
            "token",
        )

        self.assertEqual(logs, "Followed did:...safe")

    def test_collect_workflow_activity_does_not_retry_expired_or_cached_runs(self):
        existing = {
            "workflow_activity": {
                "expired_before": "2026-08-20T00:00:00+00:00",
                "runs": [
                    {
                        "id": 2,
                        "attempt": 1,
                        "workflow": "bluesky_follows_and_likes",
                        "created_at": "2026-08-21T00:00:00Z",
                        "follows": 3,
                        "unfollows": 0,
                        "follow_back_candidates": 3,
                    }
                ],
            }
        }
        workflow_runs = [
            {
                "id": 1,
                "run_attempt": 1,
                "name": "bluesky_follows_and_likes",
                "conclusion": "success",
                "created_at": "2026-08-19T00:00:00Z",
            },
            {
                "id": 2,
                "run_attempt": 1,
                "name": "bluesky_follows_and_likes",
                "conclusion": "success",
                "created_at": "2026-08-21T00:00:00Z",
            },
        ]

        with patch.object(dashboard, "fetch_workflow_run_logs") as fetch_logs:
            activity = dashboard.collect_workflow_activity(
                object(),
                "owner/repository",
                "token",
                workflow_runs,
                existing,
                datetime(2026, 8, 22, tzinfo=timezone.utc),
            )

        fetch_logs.assert_not_called()
        self.assertEqual(activity["expired_before"], "2026-08-20T00:00:00+00:00")
        self.assertEqual([item["id"] for item in activity["runs"]], [2])

    def test_collect_workflow_activity_upgrades_cached_social_run_once(self):
        existing = {
            "workflow_activity": {
                "runs": [
                    {
                        "id": 2,
                        "attempt": 1,
                        "workflow": "bluesky_follows_and_likes",
                        "created_at": "2026-08-21T00:00:00Z",
                        "follows": 3,
                        "unfollows": 0,
                    }
                ],
            }
        }
        workflow_runs = [
            {
                "id": 2,
                "run_attempt": 1,
                "name": "bluesky_follows_and_likes",
                "conclusion": "success",
                "created_at": "2026-08-21T00:00:00Z",
            }
        ]
        log_text = (
            "Social summary: follow_back_candidates=5, follow_back_added=2, "
            "protected=1, interaction_candidates=4, interaction_eligible=3, "
            "interaction_added=1, interactions_liked=2, failed=0, dry_run=false."
        )

        with patch.object(
            dashboard, "fetch_workflow_run_logs", return_value=log_text
        ) as fetch_logs:
            activity = dashboard.collect_workflow_activity(
                object(),
                "owner/repository",
                "token",
                workflow_runs,
                existing,
                datetime(2026, 8, 22, tzinfo=timezone.utc),
            )

        fetch_logs.assert_called_once()
        self.assertEqual(activity["runs"][0]["follow_back_candidates"], 5)
        self.assertEqual(activity["runs"][0]["interaction_eligible"], 3)
        with patch.object(dashboard, "fetch_workflow_run_logs") as fetch_logs:
            dashboard.collect_workflow_activity(
                object(),
                "owner/repository",
                "token",
                workflow_runs,
                {"workflow_activity": activity},
                datetime(2026, 8, 22, tzinfo=timezone.utc),
            )
        fetch_logs.assert_not_called()

    def test_collect_workflow_activity_upgrades_legacy_discovery_once(self):
        existing = {
            "workflow_activity": {
                "runs": [
                    {
                        "id": 2,
                        "attempt": 1,
                        "created_at": "2026-08-21T00:00:00Z",
                        "follows": 3,
                        "unfollows": 0,
                    }
                ],
            }
        }
        workflow_runs = [
            {
                "id": 2,
                "run_attempt": 1,
                "name": "bluesky_follow_fellows",
                "conclusion": "success",
                "created_at": "2026-08-21T00:00:00Z",
            }
        ]

        with patch.object(
            dashboard,
            "fetch_workflow_run_logs",
            return_value=(
                "Discovery summary: selected=5, followed=3, failed=2, dry_run=false."
            ),
        ) as fetch_logs:
            activity = dashboard.collect_workflow_activity(
                object(),
                "owner/repository",
                "token",
                workflow_runs,
                existing,
                datetime(2026, 8, 22, tzinfo=timezone.utc),
            )

        fetch_logs.assert_called_once()
        self.assertEqual(
            activity["runs"],
            [
                {
                    "id": 2,
                    "attempt": 1,
                    "workflow": "bluesky_follow_fellows",
                    "created_at": "2026-08-21T00:00:00Z",
                    "follows": 3,
                    "unfollows": 0,
                    "selected": 5,
                    "failed": 2,
                }
            ],
        )

        complete_existing = {"workflow_activity": activity}
        with patch.object(dashboard, "fetch_workflow_run_logs") as fetch_logs:
            dashboard.collect_workflow_activity(
                object(),
                "owner/repository",
                "token",
                workflow_runs,
                complete_existing,
                datetime(2026, 8, 22, tzinfo=timezone.utc),
            )

        fetch_logs.assert_not_called()

    def test_collect_workflow_activity_marks_expired_legacy_discovery(self):
        existing = {
            "workflow_activity": {
                "runs": [
                    {
                        "id": 2,
                        "attempt": 1,
                        "created_at": "2026-08-21T00:00:00Z",
                        "follows": 3,
                        "unfollows": 0,
                    }
                ],
            }
        }
        workflow_runs = [
            {
                "id": 2,
                "run_attempt": 1,
                "name": "bluesky_follow_fellows",
                "conclusion": "success",
                "created_at": "2026-08-21T00:00:00Z",
            }
        ]
        response = dashboard.requests.Response()
        response.status_code = 410
        expired = dashboard.requests.HTTPError(response=response)

        with patch.object(
            dashboard, "fetch_workflow_run_logs", side_effect=expired
        ) as fetch_logs:
            activity = dashboard.collect_workflow_activity(
                object(),
                "owner/repository",
                "token",
                workflow_runs,
                existing,
                datetime(2026, 8, 22, tzinfo=timezone.utc),
            )

        fetch_logs.assert_called_once()
        self.assertEqual(activity["expired_before"], "2026-08-21T00:00:00+00:00")
        self.assertEqual(activity["coverage_start"], "2026-08-21T00:00:00+00:00")
        self.assertEqual(activity["runs"], existing["workflow_activity"]["runs"])
        self.assertEqual(dashboard._discovery_metrics(activity)["completed_runs"], 0)

    def test_collect_workflow_activity_upgrades_cached_unfollow_once(self):
        existing = {
            "workflow_activity": {
                "runs": [
                    {
                        "id": 3,
                        "attempt": 1,
                        "workflow": "bluesky_unfollow",
                        "created_at": "2026-08-21T00:00:00Z",
                        "follows": 0,
                        "unfollows": 4,
                    }
                ],
            }
        }
        workflow_runs = [
            {
                "id": 3,
                "run_attempt": 1,
                "name": "bluesky_unfollow",
                "conclusion": "success",
                "created_at": "2026-08-21T00:00:00Z",
            }
        ]
        log_text = (
            "Found 9 users to unfollow (excluding ignorable accounts).\n"
            "Summary: processed=5, unfollowed=4, failed=1, missing_uri=0."
        )

        with patch.object(
            dashboard, "fetch_workflow_run_logs", return_value=log_text
        ) as fetch_logs:
            activity = dashboard.collect_workflow_activity(
                object(),
                "owner/repository",
                "token",
                workflow_runs,
                existing,
                datetime(2026, 8, 22, tzinfo=timezone.utc),
            )

        fetch_logs.assert_called_once()
        self.assertEqual(activity["runs"][0]["eligible"], 9)
        self.assertEqual(activity["runs"][0]["processed"], 5)
        with patch.object(dashboard, "fetch_workflow_run_logs") as fetch_logs:
            dashboard.collect_workflow_activity(
                object(),
                "owner/repository",
                "token",
                workflow_runs,
                {"workflow_activity": activity},
                datetime(2026, 8, 22, tzinfo=timezone.utc),
            )
        fetch_logs.assert_not_called()

    def test_collect_workflow_activity_upgrades_cached_provider_run_once(self):
        existing = {
            "workflow_activity": {
                "runs": [
                    {
                        "id": 4,
                        "attempt": 1,
                        "workflow": "bluesky_post_joke",
                        "created_at": "2026-08-21T00:00:00Z",
                        "follows": 0,
                        "unfollows": 0,
                    }
                ]
            }
        }
        workflow_runs = [
            {
                "id": 4,
                "run_attempt": 1,
                "name": "bluesky_post_joke",
                "conclusion": "success",
                "created_at": "2026-08-21T00:00:00Z",
            }
        ]
        log_text = bluesky_post_joke._provider_summary_line([], "jokeapi", True)

        with patch.object(
            dashboard, "fetch_workflow_run_logs", return_value=log_text
        ) as fetch_logs:
            activity = dashboard.collect_workflow_activity(
                object(),
                "owner/repository",
                "token",
                workflow_runs,
                existing,
                datetime(2026, 8, 22, tzinfo=timezone.utc),
            )

        fetch_logs.assert_called_once()
        self.assertEqual(activity["runs"][0]["provider_attempts"], 1)
        self.assertEqual(activity["runs"][0]["successful_source"], "jokeapi")
        with patch.object(dashboard, "fetch_workflow_run_logs") as fetch_logs:
            dashboard.collect_workflow_activity(
                object(),
                "owner/repository",
                "token",
                workflow_runs,
                {"workflow_activity": activity},
                datetime(2026, 8, 22, tzinfo=timezone.utc),
            )
        fetch_logs.assert_not_called()

    def test_summarises_discovery_runs_without_identifiers(self):
        activity = {
            "window_days": 30,
            "runs": [
                {
                    "workflow": "bluesky_follow_fellows",
                    "created_at": "2026-08-20T01:10:00Z",
                    "selected": 8,
                    "follows": 6,
                    "failed": 2,
                },
                {
                    "workflow": "bluesky_follow_fellows",
                    "created_at": "2026-08-22T01:10:00Z",
                    "selected": 5,
                    "follows": 0,
                    "failed": 5,
                },
                {
                    "workflow": "bluesky_follows_and_likes",
                    "created_at": "2026-08-22T02:20:00Z",
                    "follows": 3,
                },
            ],
        }

        summary = dashboard._discovery_metrics(activity)

        self.assertEqual(summary["completed_runs"], 2)
        self.assertEqual(summary["selected"], 13)
        self.assertEqual(summary["followed"], 6)
        self.assertEqual(summary["failed"], 7)
        self.assertEqual(summary["completion_rate"], 46.2)
        self.assertEqual(summary["average_per_run"], 3.0)
        self.assertEqual(summary["median_per_run"], 3.0)
        self.assertEqual(summary["zero_result_runs"], 1)
        self.assertNotIn("id", json.dumps(summary))

    def test_summarises_social_and_network_activity_without_identifiers(self):
        now = datetime(2026, 8, 22, 12, tzinfo=timezone.utc)
        activity = {
            "runs": [
                {
                    "workflow": "bluesky_follows_and_likes",
                    "created_at": "2026-08-22T10:00:00Z",
                    "follow_back_candidates": 8,
                    "follow_back_added": 5,
                    "protected": 3,
                    "interaction_candidates": 12,
                    "interaction_eligible": 4,
                    "interaction_added": 3,
                    "interactions_liked": 7,
                    "failed": 2,
                },
                {
                    "workflow": "bluesky_unfollow",
                    "created_at": "2026-08-01T13:00:00Z",
                    "eligible": 9,
                    "processed": 5,
                    "unfollows": 4,
                    "failed": 1,
                    "missing_uri": 0,
                    "stopped_early": True,
                },
            ]
        }
        state = {
            "follow_grace": {
                "entries": [
                    {
                        "did": "did:private:one",
                        "followed_at": now.timestamp(),
                        "source": "follow_fellows",
                    },
                    {
                        "did": "did:private:two",
                        "followed_at": now.timestamp(),
                        "source": "interaction",
                    },
                ]
            }
        }

        social = dashboard._social_activity_metrics(activity)
        network = dashboard._network_maintenance_metrics(state, activity, now)

        self.assertEqual(social["follow_back_added"], 5)
        self.assertEqual(social["interaction_added"], 3)
        self.assertEqual(social["interactions_liked"], 7)
        self.assertEqual(network["response_window"]["active"], 2)
        self.assertEqual(network["response_window"]["by_source"]["discovery"], 1)
        self.assertEqual(network["unfollow"]["cap_remaining"], 4)
        self.assertEqual(network["unfollow"]["stopped_early_runs"], 1)
        public_metrics = json.dumps({"social": social, "network": network})
        self.assertNotIn("did:private", public_metrics)
        self.assertNotIn('"id"', public_metrics)

    def test_reconstructs_following_and_posts_without_inventing_followers(self):
        now = datetime(2026, 8, 22, 6, tzinfo=timezone.utc)
        state = {
            "posted_jokes": [
                {"ts": datetime(2026, 8, 21, tzinfo=timezone.utc).timestamp()}
            ],
            "unfollow_history": {"entries": []},
        }
        activity = {
            "coverage_start": "2026-08-20T00:00:00+00:00",
            "runs": [
                {
                    "id": 1,
                    "created_at": "2026-08-21T12:00:00Z",
                    "follows": 5,
                    "unfollows": 1,
                }
            ],
        }

        snapshots = dashboard._reconstructed_snapshots(
            {"following": 100, "profile_posts": 10}, state, activity, now
        )
        by_day = {item["collected_at"][:10]: item for item in snapshots}

        self.assertEqual(by_day["2026-08-21"]["following"], 100)
        self.assertEqual(by_day["2026-08-20"]["following"], 96)
        self.assertEqual(by_day["2026-08-20"]["profile_posts"], 9)
        self.assertIsNone(by_day["2026-08-20"]["followers"])

    def test_workflow_metrics_summarise_rolling_runs(self):
        now = datetime(2026, 8, 22, 6, tzinfo=timezone.utc)
        runs = [
            {
                "name": "python_tests",
                "status": "completed",
                "conclusion": "success",
                "created_at": "2026-08-22T05:00:00Z",
                "updated_at": "2026-08-22T05:02:00Z",
            },
            {
                "name": "python_tests",
                "conclusion": "failure",
                "created_at": "2026-08-21T05:00:00Z",
            },
            {
                "name": "codeql",
                "status": "in_progress",
                "conclusion": None,
                "created_at": "2026-08-22T05:30:00Z",
            },
            {
                "name": "bluesky_post_joke",
                "conclusion": "success",
                "created_at": "2026-08-22T04:00:00Z",
            },
        ]

        summary = dashboard._workflow_metrics(runs, now)

        self.assertEqual(summary["runs"], 4)
        self.assertEqual(summary["successful"], 2)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["success_rate"], 66.7)
        tests = next(
            item for item in summary["workflows"] if item["name"] == "python_tests"
        )
        self.assertEqual(tests["last_conclusion"], "success")
        self.assertEqual(tests["last_status"], "completed")
        self.assertEqual(tests["latest_duration_seconds"], 120)
        self.assertEqual(tests["median_duration_seconds"], 120)
        post_joke = next(
            item for item in summary["workflows"] if item["name"] == "bluesky_post_joke"
        )
        self.assertEqual(post_joke["expected_interval_hours"], 4.0)
        codeql = next(item for item in summary["workflows"] if item["name"] == "codeql")
        self.assertEqual(codeql["last_status"], "in_progress")
        self.assertIsNone(codeql["last_conclusion"])
        starter_pack = next(
            item
            for item in summary["workflows"]
            if item["name"] == "bluesky_manage_starter_pack"
        )
        self.assertEqual(starter_pack["runs"], 0)
        self.assertIsNone(starter_pack["last_conclusion"])
        self.assertIsNone(starter_pack["median_duration_seconds"])

    def test_summarises_posting_delivery_without_counting_incomplete_day(self):
        now = datetime(2026, 8, 22, 12, tzinfo=timezone.utc)
        start = datetime(2026, 8, 15, tzinfo=timezone.utc)
        slots = [
            start + timedelta(days=day, hours=hour)
            for day in range(7)
            for hour in (0, 4, 8, 12, 16, 20)
        ]
        publications = [slot for slot in slots if slot != slots[3]]
        publications[4] += timedelta(minutes=45)
        publications.extend(
            datetime(2026, 8, 22, hour, tzinfo=timezone.utc) for hour in (0, 4, 8)
        )
        state = {
            "posted_jokes": [
                {"ts": publication.timestamp()} for publication in publications
            ]
        }

        delivery = dashboard._posting_delivery(state, "0 0,4,8,12,16,20 * * *", now)

        self.assertEqual(delivery["windows"]["7"]["expected"], 42)
        self.assertEqual(delivery["windows"]["7"]["delivered"], 41)
        self.assertEqual(delivery["windows"]["7"]["missed"], 1)
        self.assertEqual(delivery["windows"]["7"]["delayed"], 1)
        self.assertEqual(delivery["windows"]["7"]["delivery_rate"], 97.6)
        self.assertEqual(delivery["current_streak"], 41)

    def test_operational_alerts_use_aggregate_current_conditions(self):
        now = datetime(2026, 8, 22, 12, tzinfo=timezone.utc)
        automation = {
            "workflows": [
                {
                    "name": "bluesky_post_joke",
                    "last_conclusion": "failure",
                    "last_run_at": "2026-08-22T11:00:00Z",
                },
                {
                    "name": "python_tests",
                    "last_conclusion": "failure",
                    "last_run_at": "2026-08-22T11:00:00Z",
                },
                {
                    "name": "bluesky_dashboard",
                    "last_conclusion": "success",
                    "last_run_at": "2026-08-22T01:00:00Z",
                    "expected_interval_hours": 6.0,
                },
            ]
        }
        providers = {
            "providers": [
                {"configured": True, "healthy": False},
                {"configured": False, "healthy": False},
            ]
        }
        delivery = {"windows": {"7": {"missed": 2}}}

        alerts = dashboard._operational_alerts(automation, providers, delivery, now)

        self.assertEqual(
            alerts,
            [
                {
                    "level": "attention",
                    "kind": "workflow_failure",
                    "workflow": "bluesky_post_joke",
                },
                {
                    "level": "attention",
                    "kind": "workflow_overdue",
                    "workflow": "bluesky_dashboard",
                },
                {"level": "attention", "kind": "provider_health", "count": 1},
                {
                    "level": "attention",
                    "kind": "posting_delivery",
                    "count": 2,
                    "window_days": 7,
                },
            ],
        )

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
