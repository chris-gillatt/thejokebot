import base64
import datetime as dt
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import bluesky_common
import bluesky_follower_utils
import bluesky_generate_followers
import bluesky_post_joke
import bluesky_verify_latest_joke_post


class RuntimeControlTests(unittest.TestCase):
    def test_get_runtime_controls_parses_env_values(self):
        with mock.patch.dict(
            os.environ,
            {
                "BLUESKY_DRY_RUN": "true",
                "BLUESKY_ACTION_DELAY_SECONDS": "1.5",
            },
            clear=False,
        ):
            controls = bluesky_common.get_runtime_controls()

        self.assertTrue(controls["dry_run"])
        self.assertEqual(controls["action_delay_seconds"], 1.5)


class JokeHistoryTests(unittest.TestCase):
    def test_load_recent_jokes_filters_old_and_invalid_rows(self):
        now = 1_000_000
        recent_joke = "recent joke"
        old_joke = "old joke"
        recent_encoded = base64.b64encode(recent_joke.encode("utf-8")).decode()
        old_encoded = base64.b64encode(old_joke.encode("utf-8")).decode()

        with tempfile.TemporaryDirectory() as temp_dir:
            jokes_file = os.path.join(temp_dir, "posted_jokes.txt")
            with open(jokes_file, "w", encoding="utf-8") as handle:
                handle.write(f"{now - 10} {recent_encoded}\n")
                handle.write(f"{now - (91 * 86400)} {old_encoded}\n")
                handle.write("not-a-timestamp broken\n")

            with mock.patch.object(bluesky_post_joke, "POSTED_JOKES_FILE", jokes_file), mock.patch.object(
                bluesky_post_joke, "get_current_epoch", return_value=now
            ):
                recent = bluesky_post_joke.load_recent_jokes()

        self.assertEqual(recent, {recent_encoded})

    def test_clear_old_jokes_keeps_recent_rows_only(self):
        now = 1_000_000
        recent_encoded = base64.b64encode(b"recent").decode()
        old_encoded = base64.b64encode(b"old").decode()

        with tempfile.TemporaryDirectory() as temp_dir:
            jokes_file = os.path.join(temp_dir, "posted_jokes.txt")
            with open(jokes_file, "w", encoding="utf-8") as handle:
                handle.write(f"{now - 10} {recent_encoded}\n")
                handle.write(f"{now - (91 * 86400)} {old_encoded}\n")
                handle.write("bad-row\n")

            with mock.patch.object(bluesky_post_joke, "POSTED_JOKES_FILE", jokes_file), mock.patch.object(
                bluesky_post_joke, "get_current_epoch", return_value=now
            ):
                bluesky_post_joke.clear_old_jokes()

            with open(jokes_file, "r", encoding="utf-8") as handle:
                remaining = handle.read().strip().splitlines()

        self.assertEqual(remaining, [f"{now - 10} {recent_encoded}"])

    def test_build_hashtag_facets_uses_correct_byte_offsets(self):
        joke = "Hello"
        hashtags = ["#jokes", "#funny"]

        facets = bluesky_post_joke.build_hashtag_facets(joke, hashtags)

        self.assertEqual(facets[0]["index"]["byteStart"], len(joke.encode("utf-8")) + 2)
        self.assertEqual(
            facets[0]["index"]["byteEnd"],
            len(joke.encode("utf-8")) + 2 + len("#jokes".encode("utf-8")),
        )
        self.assertEqual(facets[1]["features"][0]["tag"], "funny")


class PaginationTests(unittest.TestCase):
    def test_fetch_paginated_data_collects_multiple_pages(self):
        responses = [
            SimpleNamespace(follows=[SimpleNamespace(did="did:one")], cursor="next"),
            SimpleNamespace(follows=[SimpleNamespace(did="did:two")], cursor=None),
        ]

        def client_method(actor, cursor=None, limit=100):
            if cursor is None:
                return responses[0]
            return responses[1]

        data = bluesky_follower_utils.fetch_paginated_data(client_method, actor="did:test")

        self.assertEqual([item.did for item in data], ["did:one", "did:two"])

    def test_fetch_paginated_data_stops_on_repeated_cursor(self):
        response = SimpleNamespace(followers=[SimpleNamespace(did="did:one")], cursor="same")

        def client_method(actor, cursor=None, limit=100):
            return response

        data = bluesky_follower_utils.fetch_paginated_data(client_method, actor="did:test")

        self.assertEqual([item.did for item in data], ["did:one"])


class FollowerSelectionTests(unittest.TestCase):
    def test_select_users_deduplicates_and_redistributes(self):
        tag_users = {
            "followback": ["did:1", "did:2", "did:3"],
            "dadjoke": ["did:2", "did:4"],
            "jokes": ["did:5"],
        }

        selected = bluesky_generate_followers.select_users(
            tag_users,
            ["followback", "dadjoke", "jokes"],
            per_tag_limit=1,
            overall_limit=4,
        )

        self.assertEqual(
            selected,
            [
                ("followback", "did:1"),
                ("dadjoke", "did:2"),
                ("jokes", "did:5"),
                ("followback", "did:3"),
            ],
        )


class VerificationHelperTests(unittest.TestCase):
    def test_parse_created_at_handles_z_suffix(self):
        parsed = bluesky_verify_latest_joke_post.parse_created_at("2026-04-18T01:29:19.486797Z")
        self.assertEqual(parsed.tzinfo, dt.timezone.utc)
        self.assertEqual(parsed.year, 2026)

    def test_has_required_hashtags_is_case_insensitive(self):
        text = "Some joke #Jokes #DadJoke #Funny"
        self.assertTrue(bluesky_verify_latest_joke_post.has_required_hashtags(text))

    def test_to_post_url_builds_expected_url(self):
        url = bluesky_verify_latest_joke_post.to_post_url(
            "thejokebot.bsky.social", "at://did:plc:abc/app.bsky.feed.post/1234"
        )
        self.assertEqual(url, "https://bsky.app/profile/thejokebot.bsky.social/post/1234")


if __name__ == "__main__":
    unittest.main()
