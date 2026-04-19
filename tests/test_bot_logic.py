import base64
import datetime as dt
import os
import unittest
from types import SimpleNamespace
from unittest import mock

import bluesky_common
import bluesky_follower_utils
import bluesky_generate_followers
import bluesky_joke_providers
import bluesky_post_joke
import bluesky_state
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


class StateProviderRotationTests(unittest.TestCase):
    def test_get_next_provider_starts_with_first_in_rotation(self):
        state = bluesky_state._default_state()
        self.assertEqual(bluesky_state.get_next_provider(state), "icanhazdadjoke")

    def test_get_next_provider_alternates_after_first(self):
        state = bluesky_state._default_state()
        state["provider"]["last_used"] = "icanhazdadjoke"
        self.assertEqual(bluesky_state.get_next_provider(state), "jokeapi")

    def test_get_next_provider_wraps_back_to_first(self):
        state = bluesky_state._default_state()
        state["provider"]["last_used"] = "jokeapi"
        self.assertEqual(bluesky_state.get_next_provider(state), "icanhazdadjoke")

    def test_get_next_provider_honours_valid_override(self):
        state = bluesky_state._default_state()
        state["provider"]["last_used"] = "icanhazdadjoke"
        self.assertEqual(bluesky_state.get_next_provider(state, override="jokeapi"), "jokeapi")

    def test_get_next_provider_ignores_unknown_override(self):
        state = bluesky_state._default_state()
        # Unknown override falls back to rotation from the start.
        result = bluesky_state.get_next_provider(state, override="nonexistent")
        self.assertEqual(result, "icanhazdadjoke")

    def test_api_ninjas_is_not_in_primary_rotation(self):
        state = bluesky_state._default_state()
        self.assertEqual(state["provider"]["rotation_order"], ["icanhazdadjoke", "jokeapi"])


class StateJokeHistoryTests(unittest.TestCase):
    def test_get_recent_b64s_filters_by_cutoff(self):
        state = bluesky_state._default_state()
        state["posted_jokes"] = [
            {"ts": 1000, "b64": "recent", "provider": "icanhazdadjoke"},
            {"ts": 1,    "b64": "old",    "provider": "icanhazdadjoke"},
        ]
        result = bluesky_state.get_recent_b64s(state, cutoff_ts=500)
        self.assertEqual(result, {"recent"})

    def test_prune_old_jokes_removes_old_entries(self):
        state = bluesky_state._default_state()
        state["posted_jokes"] = [
            {"ts": 1000, "b64": "recent", "provider": "icanhazdadjoke"},
            {"ts": 1,    "b64": "old",    "provider": "icanhazdadjoke"},
        ]
        bluesky_state.prune_old_jokes(state, cutoff_ts=500)
        self.assertEqual(len(state["posted_jokes"]), 1)
        self.assertEqual(state["posted_jokes"][0]["b64"], "recent")

    def test_record_failure_increments_count_and_records_error(self):
        state = bluesky_state._default_state()
        bluesky_state.record_failure(state, "jokeapi", "HTTP 429")
        bluesky_state.record_failure(state, "jokeapi", "HTTP 429")
        failures = state["provider"]["failures"]["jokeapi"]
        self.assertEqual(failures["count"], 2)
        self.assertEqual(failures["last_error"], "HTTP 429")


class JokeProviderTests(unittest.TestCase):
    def test_fetch_from_icanhazdadjoke_returns_text(self):
        mock_response = mock.Mock()
        mock_response.text = "Why did the chicken cross the road?"
        mock_response.raise_for_status = mock.Mock()
        with mock.patch("bluesky_joke_providers.requests.get", return_value=mock_response):
            joke = bluesky_joke_providers.fetch_from_icanhazdadjoke()
        self.assertEqual(joke, "Why did the chicken cross the road?")

    def test_fetch_from_jokeapi_returns_single_joke(self):
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        mock_response.json.return_value = {
            "error": False, "type": "single", "joke": "I am a joke."
        }
        with mock.patch("bluesky_joke_providers.requests.get", return_value=mock_response):
            joke = bluesky_joke_providers.fetch_from_jokeapi()
        self.assertEqual(joke, "I am a joke.")

    def test_fetch_from_jokeapi_assembles_twopart_joke(self):
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        mock_response.json.return_value = {
            "error": False, "type": "twopart",
            "setup": "Why did the dev quit?",
            "delivery": "Because he didn't get arrays.",
        }
        with mock.patch("bluesky_joke_providers.requests.get", return_value=mock_response):
            joke = bluesky_joke_providers.fetch_from_jokeapi()
        self.assertIn("Why did the dev quit?", joke)
        self.assertIn("Because he didn't get arrays.", joke)

    def test_fetch_from_jokeapi_raises_on_api_error_flag(self):
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        mock_response.json.return_value = {"error": True, "message": "No jokes found"}
        with mock.patch("bluesky_joke_providers.requests.get", return_value=mock_response):
            with self.assertRaises(ValueError):
                bluesky_joke_providers.fetch_from_jokeapi()

    def test_fetch_from_api_ninjas_requires_api_key(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            with mock.patch.dict(os.environ, {"API_NINJAS_API_KEY": ""}, clear=False):
                with self.assertRaises(ValueError):
                    bluesky_joke_providers.fetch_from_api_ninjas()

    def test_fetch_from_api_ninjas_returns_joke(self):
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        mock_response.json.return_value = [{"joke": "Backup joke."}]
        with mock.patch.dict(os.environ, {"API_NINJAS_API_KEY": "secret"}, clear=False):
            with mock.patch("bluesky_joke_providers.requests.get", return_value=mock_response):
                joke = bluesky_joke_providers.fetch_from_api_ninjas()
        self.assertEqual(joke, "Backup joke.")


class FacetTests(unittest.TestCase):
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
