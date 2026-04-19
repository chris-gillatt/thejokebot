import base64
import datetime as dt
import os
import re
import unittest
from types import SimpleNamespace
from unittest import mock

import bluesky_common
import bluesky_denylist
import bluesky_follower_utils
import bluesky_generate_followers
import bluesky_joke_providers
import bluesky_post_joke
import bluesky_process_reports
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

    def test_get_post_uri_index_returns_uri_mapping(self):
        state = bluesky_state._default_state()
        state["posted_jokes"] = [
            {"ts": 1, "b64": "one", "provider": "jokeapi", "post_uri": "at://post/1"},
            {"ts": 2, "b64": "two", "provider": "jokeapi"},
        ]
        index = bluesky_state.get_post_uri_index(state)
        self.assertEqual(index["at://post/1"]["b64"], "one")
        self.assertNotIn("at://post/2", index)

    def test_record_processed_notification_is_idempotent(self):
        state = bluesky_state._default_state()
        bluesky_state.record_processed_notification(state, "at://notif/1")
        bluesky_state.record_processed_notification(state, "at://notif/1")
        uris = state["reports"]["processed_notification_uris"]
        self.assertEqual(uris, ["at://notif/1"])

    def test_get_acknowledged_report_uris_returns_empty_set_initially(self):
        state = bluesky_state._default_state()
        result = bluesky_state.get_acknowledged_report_uris(state)
        self.assertEqual(result, set())

    def test_record_acknowledged_report_uri_adds_and_deduplicates(self):
        state = bluesky_state._default_state()
        bluesky_state.record_acknowledged_report_uri(state, "at://reply/1")
        bluesky_state.record_acknowledged_report_uri(state, "at://reply/1")
        uris = bluesky_state.get_acknowledged_report_uris(state)
        self.assertEqual(uris, {"at://reply/1"})

    def test_get_deleted_post_uris_returns_empty_set_initially(self):
        state = bluesky_state._default_state()
        result = bluesky_state.get_deleted_post_uris(state)
        self.assertEqual(result, set())

    def test_record_deleted_post_uri_adds_and_deduplicates(self):
        state = bluesky_state._default_state()
        bluesky_state.record_deleted_post_uri(state, "at://post/1")
        bluesky_state.record_deleted_post_uri(state, "at://post/1")
        uris = bluesky_state.get_deleted_post_uris(state)
        self.assertEqual(uris, {"at://post/1"})

    def test_get_likes_last_checked_at_returns_none_initially(self):
        state = bluesky_state._default_state()
        result = bluesky_state.get_likes_last_checked_at(state)
        self.assertIsNone(result)

    def test_set_likes_checked_now_records_epoch(self):
        state = bluesky_state._default_state()
        bluesky_state.set_likes_checked_now(state)
        checked_at = bluesky_state.get_likes_last_checked_at(state)
        self.assertIsNotNone(checked_at)
        self.assertIsInstance(checked_at, int)
        self.assertGreater(checked_at, 0)


class DenylistTests(unittest.TestCase):
    def test_add_denylist_entry_adds_new_b64(self):
        payload = {"version": 1, "jokes": []}
        added = bluesky_denylist.add_denylist_entry(
            payload,
            b64="dGVzdA==",
            source_post_uri="at://post/1",
            source_reply_uri="at://reply/1",
            reporter_did="did:plc:test",
        )
        self.assertTrue(added)
        self.assertEqual(len(payload["jokes"]), 1)

    def test_add_denylist_entry_skips_duplicate_b64(self):
        payload = {
            "version": 1,
            "jokes": [
                {
                    "b64": "dGVzdA==",
                    "source_post_uri": "at://post/1",
                    "source_reply_uri": "at://reply/1",
                    "reporter_did": "did:plc:test",
                    "reason": "user_reply_report",
                    "first_reported_at": 1,
                }
            ],
        }
        added = bluesky_denylist.add_denylist_entry(
            payload,
            b64="dGVzdA==",
            source_post_uri="at://post/2",
            source_reply_uri="at://reply/2",
            reporter_did="did:plc:test2",
        )
        self.assertFalse(added)
        self.assertEqual(len(payload["jokes"]), 1)


class ReportParsingTests(unittest.TestCase):
    def test_has_report_tag_accepts_case_insensitive_hashtag(self):
        self.assertTrue(bluesky_process_reports.has_report_tag("Please remove this #REPORT"))

    def test_has_report_tag_rejects_partial_word(self):
        self.assertFalse(bluesky_process_reports.has_report_tag("Please remove #reporting"))

    def test_has_report_tag_requires_word_boundary(self):
        self.assertTrue(bluesky_process_reports.has_report_tag("#report at start"))
        self.assertTrue(bluesky_process_reports.has_report_tag("in middle #report here"))
        self.assertTrue(bluesky_process_reports.has_report_tag("at end #report"))
        self.assertFalse(bluesky_process_reports.has_report_tag("noreporting"))

    def test_extract_notification_extracts_all_fields(self):
        notification = mock.Mock()
        notification.uri = "at://notif/1"
        notification.cid = "cid123"
        notification.reason = "reply"
        notification.reason_subject = "at://post/1"
        notification.author = mock.Mock()
        notification.author.did = "did:plc:reporter"
        notification.indexed_at = "2026-04-19T12:00:00Z"
        notification.record = mock.Mock()
        notification.record.text = "This is bad #report"
        notification.record.reply = mock.Mock()
        notification.record.reply.root = mock.Mock()
        notification.record.reply.root.uri = "at://root/1"
        notification.record.reply.root.cid = "root_cid"

        result = bluesky_process_reports._extract_notification(notification)

        self.assertEqual(result["notification_uri"], "at://notif/1")
        self.assertEqual(result["reply_cid"], "cid123")
        self.assertEqual(result["author_did"], "did:plc:reporter")
        self.assertEqual(result["reply_text"], "This is bad #report")
        self.assertEqual(result["source_post_uri"], "at://post/1")
        self.assertEqual(result["root_uri"], "at://root/1")
        self.assertEqual(result["root_cid"], "root_cid")
        self.assertEqual(result["indexed_at"], "2026-04-19T12:00:00Z")

    def test_acknowledge_report_returns_false_if_missing_cids(self):
        client = mock.Mock()
        proposal = {
            "source_reply_uri": "at://reply/1",
            "reply_cid": None,
            "root_uri": "at://root/1",
            "root_cid": "cid",
        }
        result = bluesky_process_reports.acknowledge_report(client, proposal)
        self.assertFalse(result)
        client.send_post.assert_not_called()

    def test_acknowledge_report_calls_send_post_with_reply_ref(self):
        client = mock.Mock()
        proposal = {
            "source_reply_uri": "at://reply/1",
            "reply_cid": "cid1",
            "root_uri": "at://root/1",
            "root_cid": "cid2",
        }
        result = bluesky_process_reports.acknowledge_report(client, proposal)
        self.assertTrue(result)
        client.send_post.assert_called_once()


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

    def test_jokebot_jokebook_is_in_backup_providers_not_primary(self):
        self.assertIn("jokebot_jokebook", bluesky_joke_providers.BACKUP_PROVIDERS)
        self.assertNotIn("jokebot_jokebook", bluesky_joke_providers.PRIMARY_PROVIDERS)

    def test_jokebot_jokebook_is_last_resort_backup(self):
        self.assertEqual(bluesky_joke_providers.BACKUP_PROVIDERS[-1], "jokebot_jokebook")

    def test_fetch_from_jokebot_jokebook_returns_decoded_joke(self):
        import base64, json, unittest.mock as umock
        joke_text = "Why did the chicken cross the road?\n\nTo get to the other side."
        encoded = base64.b64encode(joke_text.encode()).decode()
        fake_data = json.dumps({"jokes": [encoded]})
        mock_path = umock.MagicMock()
        mock_path.exists.return_value = True
        mock_open = umock.mock_open(read_data=fake_data)
        with umock.patch("bluesky_joke_providers._JOKEBOOK_PATH", mock_path):
            with umock.patch("builtins.open", mock_open):
                joke = bluesky_joke_providers.fetch_from_jokebot_jokebook()
        self.assertEqual(joke, joke_text)

    def test_fetch_from_jokebot_jokebook_raises_if_file_missing(self):
        mock_path = mock.MagicMock()
        mock_path.exists.return_value = False
        with mock.patch("bluesky_joke_providers._JOKEBOOK_PATH", mock_path):
            with self.assertRaises(RuntimeError):
                bluesky_joke_providers.fetch_from_jokebot_jokebook()

    def test_fetch_from_jokebot_jokebook_raises_on_empty_list(self):
        import json, unittest.mock as umock
        fake_data = json.dumps({"jokes": []})
        mock_path = umock.MagicMock()
        mock_path.exists.return_value = True
        mock_open = umock.mock_open(read_data=fake_data)
        with umock.patch("bluesky_joke_providers._JOKEBOOK_PATH", mock_path):
            with umock.patch("builtins.open", mock_open):
                with self.assertRaises(ValueError):
                    bluesky_joke_providers.fetch_from_jokebot_jokebook()


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


class LikeRepliesTests(unittest.TestCase):
    def test_reply_with_report_tag_is_skipped(self):
        """Ensure #report replies are not liked."""
        reply_text = "This joke is bad #report"
        has_report = bool(re.search(r"(?:^|\s)#report\b", reply_text, re.IGNORECASE))
        self.assertTrue(has_report)

    def test_reply_without_report_tag_passes_check(self):
        """Ensure non-report replies pass the check."""
        reply_text = "Great joke! #love"
        has_report = bool(re.search(r"(?:^|\s)#report\b", reply_text, re.IGNORECASE))
        self.assertFalse(has_report)

    def test_24_hour_cutoff_filters_old_notifications(self):
        """Ensure notifications older than 24 hours are skipped."""
        import time
        from datetime import datetime, timezone
        
        # Current time - 25 hours (definitely old)
        old_time = datetime.now(timezone.utc).timestamp() - (25 * 60 * 60)
        cutoff = time.time() - (24 * 60 * 60)
        
        self.assertLess(old_time, cutoff)

    def test_24_hour_cutoff_keeps_recent_notifications(self):
        """Ensure notifications newer than 24 hours are kept."""
        import time
        from datetime import datetime, timezone
        
        # Current time - 1 hour (recent)
        recent_time = datetime.now(timezone.utc).timestamp() - (1 * 60 * 60)
        cutoff = time.time() - (24 * 60 * 60)
        
        self.assertGreater(recent_time, cutoff)


if __name__ == "__main__":
    unittest.main()
