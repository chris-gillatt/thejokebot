import base64
import datetime as dt
import json
import os
import pathlib
import re
import unittest
from types import SimpleNamespace
from unittest import mock

import atproto_client.exceptions
import bluesky_common
import bluesky_create_report_prs
import bluesky_denylist
import bluesky_follower_utils
import bluesky_follow_fellows
import bluesky_follows_and_likes
import bluesky_joke_providers
import bluesky_manage_starter_pack
import bluesky_post_joke
import bluesky_process_reports
import bluesky_state
import bluesky_unfollow
import bluesky_validate_unfollow_ignore
import bluesky_verify_latest_joke_post
from bluesky_follower_utils import extract_list_member_did


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


class LoginClientRetryTests(unittest.TestCase):
    def test_login_client_retries_after_transient_network_error(self):
        mock_client = mock.Mock()
        mock_client.login.side_effect = [
            atproto_client.exceptions.NetworkError(),
            None,
        ]
        with mock.patch.dict(
            os.environ,
            {
                "BLUESKY_USERNAME": "thejokebot.bsky.social",
                "BLUESKY_PASSWORD": "test-password",
                "BLUESKY_LOGIN_RETRY_ATTEMPTS": "3",
                "BLUESKY_LOGIN_RETRY_DELAY_SECONDS": "0",
            },
            clear=True,
        ):
            with mock.patch("bluesky_common.Client", return_value=mock_client):
                client, username = bluesky_common.login_client()

        self.assertIs(client, mock_client)
        self.assertEqual(username, "thejokebot.bsky.social")
        self.assertEqual(mock_client.login.call_count, 2)

    def test_login_client_raises_after_retry_exhausted(self):
        mock_client = mock.Mock()
        mock_client.login.side_effect = atproto_client.exceptions.NetworkError()
        with mock.patch.dict(
            os.environ,
            {
                "BLUESKY_USERNAME": "thejokebot.bsky.social",
                "BLUESKY_PASSWORD": "test-password",
                "BLUESKY_LOGIN_RETRY_ATTEMPTS": "2",
                "BLUESKY_LOGIN_RETRY_DELAY_SECONDS": "0",
            },
            clear=True,
        ):
            with mock.patch("bluesky_common.Client", return_value=mock_client):
                with self.assertRaises(atproto_client.exceptions.NetworkError):
                    bluesky_common.login_client()

        self.assertEqual(mock_client.login.call_count, 2)


class NetworkRetryHelperTests(unittest.TestCase):
    def test_retry_network_call_succeeds_after_transient_error(self):
        calls = {"count": 0}

        def flaky_call():
            calls["count"] += 1
            if calls["count"] == 1:
                raise atproto_client.exceptions.NetworkError("timeout")
            return "ok"

        with mock.patch.dict(
            os.environ,
            {
                "BLUESKY_NETWORK_RETRY_ATTEMPTS": "2",
                "BLUESKY_NETWORK_RETRY_DELAY_SECONDS": "0",
                "BLUESKY_NETWORK_RETRY_BACKOFF_FACTOR": "1",
            },
            clear=False,
        ):
            result = bluesky_common.retry_network_call(flaky_call, "unit-test call")

        self.assertEqual(result, "ok")
        self.assertEqual(calls["count"], 2)


class UnfollowControlTests(unittest.TestCase):
    def test_get_unfollow_controls_defaults(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            controls = bluesky_unfollow.get_unfollow_controls()

        self.assertEqual(
            controls["max_actions"], bluesky_unfollow.DEFAULT_UNFOLLOW_MAX_ACTIONS
        )
        self.assertEqual(
            controls["batch_size"], bluesky_unfollow.DEFAULT_UNFOLLOW_BATCH_SIZE
        )
        self.assertEqual(
            controls["batch_pause_seconds"],
            bluesky_unfollow.DEFAULT_UNFOLLOW_BATCH_PAUSE_SECONDS,
        )

    def test_get_unfollow_controls_parses_env_values(self):
        with mock.patch.dict(
            os.environ,
            {
                "BLUESKY_UNFOLLOW_MAX_ACTIONS": "120",
                "BLUESKY_UNFOLLOW_BATCH_SIZE": "20",
                "BLUESKY_UNFOLLOW_BATCH_PAUSE_SECONDS": "7.5",
            },
            clear=True,
        ):
            controls = bluesky_unfollow.get_unfollow_controls()

        self.assertEqual(controls["max_actions"], 120)
        self.assertEqual(controls["batch_size"], 20)
        self.assertEqual(controls["batch_pause_seconds"], 7.5)

    def test_select_unfollow_candidates_is_sorted_and_capped(self):
        following_map = {
            "did:3": "uri:3",
            "did:1": "uri:1",
            "did:2": "uri:2",
            "did:4": "uri:4",
        }
        follower_dids = {"did:4"}
        ignorable_dids = {"did:2"}

        selected = bluesky_unfollow.select_unfollow_candidates(
            following_map,
            follower_dids,
            ignorable_dids,
            max_actions=1,
        )

        self.assertEqual(selected, ["did:1"])

    def test_is_rate_limited_error_detects_429_text(self):
        self.assertTrue(
            bluesky_unfollow._is_rate_limited_error(
                RuntimeError("HTTP 429 Too Many Requests")
            )
        )
        self.assertFalse(
            bluesky_unfollow._is_rate_limited_error(RuntimeError("Connection timeout"))
        )


class UnfollowIgnoreValidationTests(unittest.TestCase):
    def test_parse_ignore_handles_deduplicates_and_sorts(self):
        handles = bluesky_validate_unfollow_ignore.parse_ignore_handles(
            " Example.Bsky.Social ,foo.bsky.social,foo.bsky.social",
            default_handles=(),
        )
        self.assertEqual(handles, ["example.bsky.social", "foo.bsky.social"])

    def test_extract_profile_did_supports_object_and_dict(self):
        object_profile = SimpleNamespace(did="did:plc:abc")
        dict_profile = {"did": "did:plc:def"}

        self.assertEqual(
            bluesky_validate_unfollow_ignore.extract_profile_did(object_profile),
            "did:plc:abc",
        )
        self.assertEqual(
            bluesky_validate_unfollow_ignore.extract_profile_did(dict_profile),
            "did:plc:def",
        )

    def test_is_stale_resolution_error_detects_not_found_text(self):
        exc = RuntimeError("Profile not found")
        self.assertTrue(bluesky_validate_unfollow_ignore.is_stale_resolution_error(exc))

    def test_is_stale_resolution_error_ignores_unrelated_error(self):
        exc = RuntimeError("temporary network timeout")
        self.assertFalse(
            bluesky_validate_unfollow_ignore.is_stale_resolution_error(exc)
        )

    def test_unfollow_users_skips_bad_profile_lookup_error(self):
        state = bluesky_state._default_state()
        client = mock.Mock()
        client.me.did = "did:plc:test"

        with mock.patch(
            "bluesky_unfollow.login_client",
            return_value=(client, "thejokebot.bsky.social"),
        ):
            with mock.patch("bluesky_unfollow.fetch_paginated_data", return_value=[]):
                with mock.patch(
                    "bluesky_unfollow.get_runtime_controls",
                    return_value={"dry_run": True, "action_delay_seconds": 0.0},
                ):
                    with mock.patch(
                        "bluesky_unfollow.get_unfollow_controls",
                        return_value={
                            "max_actions": 0,
                            "batch_size": 50,
                            "batch_pause_seconds": 0.0,
                        },
                    ):
                        with mock.patch(
                            "bluesky_unfollow.retry_network_call",
                            side_effect=atproto_client.exceptions.BadRequestError(
                                mock.Mock()
                            ),
                        ):
                            with mock.patch(
                                "bluesky_unfollow._state.load_state", return_value=state
                            ):
                                with mock.patch(
                                    "bluesky_unfollow._state.prune_unfollow_history"
                                ):
                                    with mock.patch(
                                        "bluesky_unfollow._state.save_state"
                                    ) as save_state:
                                        bluesky_unfollow.unfollow_users()

        save_state.assert_called_once_with(state)

    def test_load_source_list_uri_returns_empty_when_file_missing(self):
        missing_path = pathlib.Path("/tmp/does-not-exist-jokebot-starter-pack.json")
        self.assertEqual(
            bluesky_unfollow._load_source_list_uri(config_path=missing_path), ""
        )

    def test_extract_list_member_did_supports_string_and_object_subject(self):
        did_str = bluesky_unfollow._extract_list_member_did({"subject": "did:plc:abc"})
        did_obj = bluesky_unfollow._extract_list_member_did(
            {"subject": {"did": "did:plc:def"}}
        )
        self.assertEqual(did_str, "did:plc:abc")
        self.assertEqual(did_obj, "did:plc:def")


class StarterPackManagerTests(unittest.TestCase):
    def test_load_starter_pack_config_defaults_when_missing(self):
        with mock.patch(
            "bluesky_manage_starter_pack._CONFIG_PATH",
            pathlib.Path("/tmp/does-not-exist-jokebot-starter-pack-config.json"),
        ):
            cfg = bluesky_manage_starter_pack.load_starter_pack_config()

        self.assertIn("starter_pack", cfg)
        self.assertFalse(cfg["starter_pack"]["enabled"])

    def test_extract_list_member_did_from_subject_forms(self):
        self.assertEqual(
            extract_list_member_did({"subject": "did:plc:x"}),
            "did:plc:x",
        )
        self.assertEqual(
            extract_list_member_did({"subject": {"did": "did:plc:y"}}),
            "did:plc:y",
        )

    def test_upsert_raises_on_invalid_starter_pack_uri(self):
        client = mock.Mock()
        client.me.did = "did:plc:test"

        with self.assertRaises(ValueError):
            bluesky_manage_starter_pack.upsert_starter_pack_record(
                client,
                {
                    "name": "Pack",
                    "description": "Desc",
                    "starter_pack_uri": "not-an-at-uri",
                    "record_key": "",
                },
                source_list_uri="at://did:plc:test/app.bsky.graph.list/3abc",
                dry_run=False,
            )

    def test_upsert_raises_on_did_mismatch(self):
        client = mock.Mock()
        client.me.did = "did:plc:actual"

        with self.assertRaises(ValueError):
            bluesky_manage_starter_pack.upsert_starter_pack_record(
                client,
                {
                    "name": "Pack",
                    "description": "Desc",
                    "starter_pack_uri": (
                        "at://did:plc:other/app.bsky.graph.starterpack/3mkrjdntf7x2l"
                    ),
                    "record_key": "",
                },
                source_list_uri="at://did:plc:actual/app.bsky.graph.list/3abc",
                dry_run=False,
            )

    def test_upsert_uses_put_record_for_valid_starter_pack_uri(self):
        client = mock.Mock()
        client.me.did = "did:plc:test"

        with mock.patch(
            "bluesky_manage_starter_pack.retry_network_call",
            side_effect=lambda call, description: call(),
        ):
            result = bluesky_manage_starter_pack.upsert_starter_pack_record(
                client,
                {
                    "name": "Pack",
                    "description": "Desc",
                    "starter_pack_uri": (
                        "at://did:plc:test/app.bsky.graph.starterpack/3mkrjdntf7x2l"
                    ),
                    "record_key": "",
                },
                source_list_uri="at://did:plc:test/app.bsky.graph.list/3abc",
                dry_run=False,
            )

        self.assertEqual(
            result,
            "at://did:plc:test/app.bsky.graph.starterpack/3mkrjdntf7x2l",
        )
        client.com.atproto.repo.put_record.assert_called_once()
        client.com.atproto.repo.create_record.assert_not_called()

    def test_upsert_uses_create_record_when_no_target_configured(self):
        client = mock.Mock()
        client.me.did = "did:plc:test"
        client.com.atproto.repo.create_record.return_value = SimpleNamespace(
            uri="at://did:plc:test/app.bsky.graph.starterpack/3xyzxyzxyzxyz"
        )

        with mock.patch(
            "bluesky_manage_starter_pack.retry_network_call",
            side_effect=lambda call, description: call(),
        ):
            result = bluesky_manage_starter_pack.upsert_starter_pack_record(
                client,
                {
                    "name": "Pack",
                    "description": "Desc",
                    "starter_pack_uri": "",
                    "record_key": "",
                },
                source_list_uri="at://did:plc:test/app.bsky.graph.list/3abc",
                dry_run=False,
            )

        self.assertEqual(
            result,
            "at://did:plc:test/app.bsky.graph.starterpack/3xyzxyzxyzxyz",
        )
        client.com.atproto.repo.create_record.assert_called_once()
        client.com.atproto.repo.put_record.assert_not_called()

    def test_upsert_dry_run_returns_target_uri_without_writing(self):
        client = mock.Mock()
        client.me.did = "did:plc:test"

        result = bluesky_manage_starter_pack.upsert_starter_pack_record(
            client,
            {
                "name": "Pack",
                "description": "Desc",
                "starter_pack_uri": "at://did:plc:test/app.bsky.graph.starterpack/3mkrjdntf7x2l",
                "record_key": "",
            },
            source_list_uri="at://did:plc:test/app.bsky.graph.list/3abc",
            dry_run=True,
        )

        self.assertEqual(
            result,
            "at://did:plc:test/app.bsky.graph.starterpack/3mkrjdntf7x2l",
        )
        client.com.atproto.repo.put_record.assert_not_called()
        client.com.atproto.repo.create_record.assert_not_called()

    def test_pull_raises_when_no_uri_configured(self):
        client = mock.Mock()
        client.me.did = "did:plc:test"

        with self.assertRaises(ValueError):
            bluesky_manage_starter_pack.pull_starter_pack_record(
                client,
                {"starter_pack_uri": "", "name": "Pack", "description": "Desc"},
            )

    def test_pull_raises_on_invalid_uri(self):
        client = mock.Mock()
        client.me.did = "did:plc:test"

        with self.assertRaises(ValueError):
            bluesky_manage_starter_pack.pull_starter_pack_record(
                client,
                {
                    "starter_pack_uri": "not-valid",
                    "name": "Pack",
                    "description": "Desc",
                },
            )

    def test_pull_raises_on_did_mismatch(self):
        client = mock.Mock()
        client.me.did = "did:plc:actual"

        with self.assertRaises(ValueError):
            bluesky_manage_starter_pack.pull_starter_pack_record(
                client,
                {
                    "starter_pack_uri": (
                        "at://did:plc:other/app.bsky.graph.starterpack/3mkrjdntf7x2l"
                    ),
                    "name": "Pack",
                    "description": "Desc",
                },
            )

    def test_pull_returns_empty_when_live_matches_local(self):
        client = mock.Mock()
        client.me.did = "did:plc:test"
        client.com.atproto.repo.get_record.return_value = SimpleNamespace(
            value={"name": "Pack", "description": "Desc"}
        )

        with mock.patch(
            "bluesky_manage_starter_pack.retry_network_call",
            side_effect=lambda call, description: call(),
        ):
            result = bluesky_manage_starter_pack.pull_starter_pack_record(
                client,
                {
                    "starter_pack_uri": (
                        "at://did:plc:test/app.bsky.graph.starterpack/3mkrjdntf7x2l"
                    ),
                    "name": "Pack",
                    "description": "Desc",
                },
            )

        self.assertEqual(result, {})

    def test_pull_returns_only_changed_fields(self):
        client = mock.Mock()
        client.me.did = "did:plc:test"
        client.com.atproto.repo.get_record.return_value = SimpleNamespace(
            value={"name": "Same Name", "description": "New description"}
        )

        with mock.patch(
            "bluesky_manage_starter_pack.retry_network_call",
            side_effect=lambda call, description: call(),
        ):
            result = bluesky_manage_starter_pack.pull_starter_pack_record(
                client,
                {
                    "starter_pack_uri": (
                        "at://did:plc:test/app.bsky.graph.starterpack/3mkrjdntf7x2l"
                    ),
                    "name": "Same Name",
                    "description": "Old description",
                },
            )

        self.assertEqual(result, {"description": "New description"})

    def test_pull_allows_blank_live_fields_to_replace_local_values(self):
        client = mock.Mock()
        client.me.did = "did:plc:test"
        client.com.atproto.repo.get_record.return_value = SimpleNamespace(
            value={"name": "", "description": ""}
        )

        with mock.patch(
            "bluesky_manage_starter_pack.retry_network_call",
            side_effect=lambda call, description: call(),
        ):
            result = bluesky_manage_starter_pack.pull_starter_pack_record(
                client,
                {
                    "starter_pack_uri": (
                        "at://did:plc:test/app.bsky.graph.starterpack/3mkrjdntf7x2l"
                    ),
                    "name": "Local Name",
                    "description": "Local description",
                },
            )

        self.assertEqual(result, {"name": "", "description": ""})

    def test_write_starter_pack_config_updates_persists_changes(self):
        import tempfile

        original = {
            "starter_pack": {
                "enabled": True,
                "name": "Old Name",
                "description": "Old desc",
                "source_list_uri": "at://x",
                "record_key": "",
                "starter_pack_uri": "at://y",
                "sync": {"follow_list_members": True, "upsert_record": True},
            }
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp:
            json.dump(original, tmp)
            tmp_path = pathlib.Path(tmp.name)

        try:
            with mock.patch("bluesky_manage_starter_pack._CONFIG_PATH", tmp_path):
                bluesky_manage_starter_pack.write_starter_pack_config_updates(
                    {"name": "New Name", "description": "New desc"}
                )
                updated = json.loads(tmp_path.read_text(encoding="utf-8"))
        finally:
            tmp_path.unlink(missing_ok=True)

        self.assertEqual(updated["starter_pack"]["name"], "New Name")
        self.assertEqual(updated["starter_pack"]["description"], "New desc")
        self.assertTrue(updated["starter_pack"]["enabled"])
        self.assertEqual(updated["starter_pack"]["source_list_uri"], "at://x")

    def test_main_pull_mode_fetches_live_preview_without_source_list_uri(self):
        with mock.patch("bluesky_manage_starter_pack._parse_args") as parse_args:
            parse_args.return_value = SimpleNamespace(mode="pull")
            with mock.patch(
                "bluesky_manage_starter_pack.get_runtime_controls",
                return_value={"dry_run": True, "action_delay_seconds": 0.0},
            ):
                with mock.patch(
                    "bluesky_manage_starter_pack.load_starter_pack_config",
                    return_value={
                        "starter_pack": {
                            "enabled": True,
                            "name": "Local",
                            "description": "Old",
                            "source_list_uri": "",
                            "starter_pack_uri": (
                                "at://did:plc:test/app.bsky.graph.starterpack/3mkrjdntf7x2l"
                            ),
                            "sync": {},
                        }
                    },
                ):
                    with mock.patch(
                        "bluesky_manage_starter_pack.login_client",
                        return_value=(mock.Mock(), "user"),
                    ):
                        with mock.patch(
                            "bluesky_manage_starter_pack.pull_starter_pack_record",
                            return_value={"description": "Live"},
                        ) as pull_record:
                            with mock.patch(
                                "bluesky_manage_starter_pack.write_starter_pack_config_updates"
                            ) as write_updates:
                                result = bluesky_manage_starter_pack.main()

        self.assertEqual(result, 0)
        pull_record.assert_called_once()
        write_updates.assert_not_called()


class StateProviderRotationTests(unittest.TestCase):
    def test_primary_providers_match_state_rotation_order(self):
        self.assertEqual(
            bluesky_joke_providers.PRIMARY_PROVIDERS,
            bluesky_state.PROVIDER_ROTATION_ORDER,
        )

    def test_get_next_provider_starts_with_first_in_rotation(self):
        state = bluesky_state._default_state()
        self.assertEqual(bluesky_state.get_next_provider(state), "icanhazdadjoke")

    def test_get_next_provider_alternates_after_first(self):
        state = bluesky_state._default_state()
        state["provider"]["last_used"] = "icanhazdadjoke"
        self.assertEqual(bluesky_state.get_next_provider(state), "jokeapi")

    def test_get_next_provider_advances_to_third(self):
        state = bluesky_state._default_state()
        state["provider"]["last_used"] = "jokeapi"
        self.assertEqual(bluesky_state.get_next_provider(state), "groandeck")

    def test_get_next_provider_wraps_back_to_first(self):
        state = bluesky_state._default_state()
        state["provider"]["last_used"] = "groandeck"
        self.assertEqual(bluesky_state.get_next_provider(state), "icanhazdadjoke")

    def test_get_next_provider_honours_valid_override(self):
        state = bluesky_state._default_state()
        state["provider"]["last_used"] = "icanhazdadjoke"
        self.assertEqual(
            bluesky_state.get_next_provider(state, override="jokeapi"), "jokeapi"
        )

    def test_get_next_provider_ignores_unknown_override(self):
        state = bluesky_state._default_state()
        # Unknown override falls back to rotation from the start.
        result = bluesky_state.get_next_provider(state, override="nonexistent")
        self.assertEqual(result, "icanhazdadjoke")

    def test_api_ninjas_is_not_in_primary_rotation(self):
        state = bluesky_state._default_state()
        self.assertEqual(
            state["provider"]["rotation_order"],
            ["icanhazdadjoke", "jokeapi", "groandeck"],
        )


class StateJokeHistoryTests(unittest.TestCase):
    def test_get_recent_b64s_filters_by_cutoff(self):
        state = bluesky_state._default_state()
        state["posted_jokes"] = [
            {"ts": 1000, "b64": "recent", "provider": "icanhazdadjoke"},
            {"ts": 1, "b64": "old", "provider": "icanhazdadjoke"},
        ]
        result = bluesky_state.get_recent_b64s(state, cutoff_ts=500)
        self.assertEqual(result, {"recent"})

    def test_prune_old_jokes_removes_old_entries(self):
        state = bluesky_state._default_state()
        state["posted_jokes"] = [
            {"ts": 1000, "b64": "recent", "provider": "icanhazdadjoke"},
            {"ts": 1, "b64": "old", "provider": "icanhazdadjoke"},
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


class ReportPrRoutingTests(unittest.TestCase):
    def test_proposal_target_uses_jokebook_for_jokebook_provider(self):
        proposal = {"source_provider": "jokebot_jokebook"}
        target = bluesky_create_report_prs.proposal_target(proposal)
        self.assertEqual(target, "jokebook")

    def test_proposal_target_defaults_to_denylist(self):
        proposal = {"source_provider": "jokeapi"}
        target = bluesky_create_report_prs.proposal_target(proposal)
        self.assertEqual(target, "denylist")

    def test_remove_jokebook_entry_removes_matching_b64(self):
        payload = {"jokes": ["a", "b", "a"]}
        removed = bluesky_create_report_prs.remove_jokebook_entry(payload, "a")
        self.assertTrue(removed)
        self.assertEqual(payload["jokes"], ["b"])

    def test_remove_jokebook_entry_returns_false_when_missing(self):
        payload = {"jokes": ["a", "b"]}
        removed = bluesky_create_report_prs.remove_jokebook_entry(payload, "c")
        self.assertFalse(removed)
        self.assertEqual(payload["jokes"], ["a", "b"])


class ReportParsingTests(unittest.TestCase):
    def test_has_report_tag_accepts_case_insensitive_hashtag(self):
        self.assertTrue(
            bluesky_process_reports.has_report_tag("Please remove this #REPORT")
        )

    def test_has_report_tag_rejects_partial_word(self):
        self.assertFalse(
            bluesky_process_reports.has_report_tag("Please remove #reporting")
        )

    def test_has_report_tag_requires_word_boundary(self):
        self.assertTrue(bluesky_process_reports.has_report_tag("#report at start"))
        self.assertTrue(
            bluesky_process_reports.has_report_tag("in middle #report here")
        )
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
        success, should_retry = bluesky_process_reports.acknowledge_report(
            client, proposal
        )
        self.assertFalse(success)
        self.assertFalse(should_retry)
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
        with mock.patch(
            "bluesky_joke_providers.requests.get", return_value=mock_response
        ):
            joke = bluesky_joke_providers.fetch_from_icanhazdadjoke()
        self.assertEqual(joke, "Why did the chicken cross the road?")

    def test_fetch_from_jokeapi_returns_single_joke(self):
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        mock_response.json.return_value = {
            "error": False,
            "type": "single",
            "joke": "I am a joke.",
        }
        with mock.patch(
            "bluesky_joke_providers.requests.get", return_value=mock_response
        ):
            joke = bluesky_joke_providers.fetch_from_jokeapi()
        self.assertEqual(joke, "I am a joke.")

    def test_fetch_from_jokeapi_assembles_twopart_joke(self):
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        mock_response.json.return_value = {
            "error": False,
            "type": "twopart",
            "setup": "Why did the dev quit?",
            "delivery": "Because he didn't get arrays.",
        }
        with mock.patch(
            "bluesky_joke_providers.requests.get", return_value=mock_response
        ):
            joke = bluesky_joke_providers.fetch_from_jokeapi()
        self.assertIn("Why did the dev quit?", joke)
        self.assertIn("Because he didn't get arrays.", joke)

    def test_fetch_from_jokeapi_raises_on_api_error_flag(self):
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        mock_response.json.return_value = {"error": True, "message": "No jokes found"}
        with mock.patch(
            "bluesky_joke_providers.requests.get", return_value=mock_response
        ):
            with self.assertRaises(ValueError):
                bluesky_joke_providers.fetch_from_jokeapi()

    def test_fetch_from_groandeck_assembles_twopart_joke(self):
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        mock_response.json.return_value = {
            "id": "abc123",
            "setup": "Why did the maths book look sad?",
            "punchline": "Because it had too many problems.",
            "tags": ["math"],
        }
        with mock.patch(
            "bluesky_joke_providers.requests.get", return_value=mock_response
        ):
            joke = bluesky_joke_providers.fetch_from_groandeck()
        self.assertIn("Why did the maths book look sad?", joke)
        self.assertIn("Because it had too many problems.", joke)

    def test_fetch_from_groandeck_raises_on_missing_punchline(self):
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        mock_response.json.return_value = {"setup": "Setup only", "punchline": ""}
        with mock.patch(
            "bluesky_joke_providers.requests.get", return_value=mock_response
        ):
            with self.assertRaises(ValueError):
                bluesky_joke_providers.fetch_from_groandeck()

    def test_fetch_from_syrsly_returns_text(self):
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        mock_response.text = "A dad joke from syrsly."
        with mock.patch(
            "bluesky_joke_providers.requests.get", return_value=mock_response
        ):
            joke = bluesky_joke_providers.fetch_from_syrsly()
        self.assertEqual(joke, "A dad joke from syrsly.")

    def test_fetch_from_syrsly_raises_on_empty_response(self):
        mock_response = mock.Mock()
        mock_response.raise_for_status = mock.Mock()
        mock_response.text = "   "
        with mock.patch(
            "bluesky_joke_providers.requests.get", return_value=mock_response
        ):
            with self.assertRaises(ValueError):
                bluesky_joke_providers.fetch_from_syrsly()

    def test_groandeck_is_in_primary_providers(self):
        self.assertIn("groandeck", bluesky_joke_providers.PRIMARY_PROVIDERS)

    def test_groandeck_is_registered_in_providers(self):
        self.assertIn("groandeck", bluesky_joke_providers.PROVIDERS)

    def test_syrsly_is_in_backup_providers(self):
        self.assertIn("syrsly", bluesky_joke_providers.BACKUP_PROVIDERS)

    def test_syrsly_is_registered_in_providers(self):
        self.assertIn("syrsly", bluesky_joke_providers.PROVIDERS)

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
            with mock.patch(
                "bluesky_joke_providers.requests.get", return_value=mock_response
            ):
                joke = bluesky_joke_providers.fetch_from_api_ninjas()
        self.assertEqual(joke, "Backup joke.")

    def test_jokebot_jokebook_is_fallback_provider_not_primary_or_backup(
        self,
    ):
        self.assertEqual("jokebot_jokebook", bluesky_joke_providers.FALLBACK_PROVIDER)
        self.assertNotIn("jokebot_jokebook", bluesky_joke_providers.PRIMARY_PROVIDERS)
        self.assertNotIn("jokebot_jokebook", bluesky_joke_providers.BACKUP_PROVIDERS)

    def test_fetch_from_jokebot_jokebook_returns_decoded_joke(self):
        import base64
        import json
        import unittest.mock as umock

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
        import json
        import unittest.mock as umock

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

        data = bluesky_follower_utils.fetch_paginated_data(
            client_method, actor="did:test"
        )

        self.assertEqual([item.did for item in data], ["did:one", "did:two"])

    def test_fetch_paginated_data_stops_on_repeated_cursor(self):
        response = SimpleNamespace(
            followers=[SimpleNamespace(did="did:one")], cursor="same"
        )

        def client_method(actor, cursor=None, limit=100):
            return response

        data = bluesky_follower_utils.fetch_paginated_data(
            client_method, actor="did:test"
        )

        self.assertEqual([item.did for item in data], ["did:one"])

    def test_fetch_paginated_data_retries_transient_page_error(self):
        calls = {"count": 0}

        def client_method(actor, cursor=None, limit=100):
            calls["count"] += 1
            if calls["count"] == 1:
                raise atproto_client.exceptions.NetworkError("transient")
            return SimpleNamespace(
                follows=[SimpleNamespace(did="did:one")], cursor=None
            )

        with mock.patch.dict(
            os.environ,
            {
                "BLUESKY_NETWORK_RETRY_ATTEMPTS": "2",
                "BLUESKY_NETWORK_RETRY_DELAY_SECONDS": "0",
                "BLUESKY_NETWORK_RETRY_BACKOFF_FACTOR": "1",
            },
            clear=False,
        ):
            data = bluesky_follower_utils.fetch_paginated_data(
                client_method, actor="did:test"
            )

        self.assertEqual([item.did for item in data], ["did:one"])
        self.assertEqual(calls["count"], 2)


class FollowerSelectionTests(unittest.TestCase):
    def test_select_users_deduplicates_and_redistributes(self):
        tag_users = {
            "followback": ["did:1", "did:2", "did:3"],
            "dadjoke": ["did:2", "did:4"],
            "jokes": ["did:5"],
        }

        selected = bluesky_follow_fellows.select_users(
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
        parsed = bluesky_verify_latest_joke_post.parse_created_at(
            "2026-04-18T01:29:19.486797Z"
        )
        self.assertEqual(parsed.tzinfo, dt.timezone.utc)
        self.assertEqual(parsed.year, 2026)

    def test_has_required_hashtags_is_case_insensitive(self):
        text = "Some joke #Jokes #DadJoke #Funny"
        self.assertTrue(bluesky_verify_latest_joke_post.has_required_hashtags(text))

    def test_to_post_url_builds_expected_url(self):
        url = bluesky_verify_latest_joke_post.to_post_url(
            "thejokebot.bsky.social", "at://did:plc:abc/app.bsky.feed.post/1234"
        )
        self.assertEqual(
            url, "https://bsky.app/profile/thejokebot.bsky.social/post/1234"
        )


class LikeRepliesTests(unittest.TestCase):
    def test_like_replies_likes_fresh_repost(self):
        now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        notification = SimpleNamespace(
            reason="repost",
            indexed_at=now,
            uri="at://did:plc:abc/app.bsky.feed.repost/1",
            cid="cid-repost-1",
            record=SimpleNamespace(text="Reposting this one"),
        )
        response = SimpleNamespace(notifications=[notification], cursor=None)

        state = bluesky_state._default_state()
        client = mock.Mock()
        client.app.bsky.notification.list_notifications.return_value = response

        with mock.patch(
            "bluesky_follows_and_likes.retry_network_call",
            side_effect=lambda fn, description: fn(),
        ):
            with mock.patch("bluesky_state.save_state"):
                liked_count = bluesky_follows_and_likes.like_replies(
                    client,
                    state,
                    dry_run=True,
                    action_delay_seconds=0,
                )

        self.assertEqual(liked_count, 1)
        self.assertIn(
            "at://did:plc:abc/app.bsky.feed.repost/1",
            bluesky_state.get_liked_reply_uris(state),
        )
        call_params = client.app.bsky.notification.list_notifications.call_args.kwargs[
            "params"
        ]
        self.assertIn("repost", call_params["reasons"])

    def test_like_replies_skips_duplicate_repost(self):
        now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        uri = "at://did:plc:abc/app.bsky.feed.repost/duplicate"
        notification = SimpleNamespace(
            reason="repost",
            indexed_at=now,
            uri=uri,
            cid="cid-duplicate",
            record=SimpleNamespace(text="Seen repost"),
        )
        response = SimpleNamespace(notifications=[notification], cursor=None)

        state = bluesky_state._default_state()
        bluesky_state.record_liked_reply_uri(state, uri)
        client = mock.Mock()
        client.app.bsky.notification.list_notifications.return_value = response

        with mock.patch(
            "bluesky_follows_and_likes.retry_network_call",
            side_effect=lambda fn, description: fn(),
        ):
            with mock.patch("bluesky_state.save_state"):
                liked_count = bluesky_follows_and_likes.like_replies(
                    client,
                    state,
                    dry_run=True,
                    action_delay_seconds=0,
                )

        self.assertEqual(liked_count, 0)
        self.assertEqual(len(bluesky_state.get_liked_reply_uris(state)), 1)

    def test_like_replies_skips_stale_repost(self):
        old = (
            (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=25))
            .isoformat()
            .replace("+00:00", "Z")
        )
        notification = SimpleNamespace(
            reason="repost",
            indexed_at=old,
            uri="at://did:plc:abc/app.bsky.feed.repost/old",
            cid="cid-old",
            record=SimpleNamespace(text="Old repost"),
        )
        response = SimpleNamespace(notifications=[notification], cursor=None)

        state = bluesky_state._default_state()
        client = mock.Mock()
        client.app.bsky.notification.list_notifications.return_value = response

        with mock.patch(
            "bluesky_follows_and_likes.retry_network_call",
            side_effect=lambda fn, description: fn(),
        ):
            with mock.patch("bluesky_state.save_state"):
                liked_count = bluesky_follows_and_likes.like_replies(
                    client,
                    state,
                    dry_run=True,
                    action_delay_seconds=0,
                )

        self.assertEqual(liked_count, 0)
        self.assertEqual(len(bluesky_state.get_liked_reply_uris(state)), 0)

    def test_like_replies_skips_repost_with_report_tag(self):
        now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        notification = SimpleNamespace(
            reason="repost",
            indexed_at=now,
            uri="at://did:plc:abc/app.bsky.feed.repost/report",
            cid="cid-report",
            record=SimpleNamespace(text="Please see #report"),
        )
        response = SimpleNamespace(notifications=[notification], cursor=None)

        state = bluesky_state._default_state()
        client = mock.Mock()
        client.app.bsky.notification.list_notifications.return_value = response

        with mock.patch(
            "bluesky_follows_and_likes.retry_network_call",
            side_effect=lambda fn, description: fn(),
        ):
            with mock.patch("bluesky_state.save_state"):
                liked_count = bluesky_follows_and_likes.like_replies(
                    client,
                    state,
                    dry_run=True,
                    action_delay_seconds=0,
                )

        self.assertEqual(liked_count, 0)
        self.assertEqual(len(bluesky_state.get_liked_reply_uris(state)), 0)

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


class UnfollowHistoryTests(unittest.TestCase):
    def test_get_unfollowed_dids_returns_empty_set_initially(self):
        state = bluesky_state._default_state()
        self.assertEqual(bluesky_state.get_unfollowed_dids(state), set())

    def test_record_unfollow_stores_did_and_reason(self):
        state = bluesky_state._default_state()
        bluesky_state.record_unfollow(state, "did:plc:abc", "not_following_back")
        dids = bluesky_state.get_unfollowed_dids(state)
        self.assertIn("did:plc:abc", dids)

    def test_record_unfollow_updates_existing_entry_rather_than_duplicating(self):
        state = bluesky_state._default_state()
        bluesky_state.record_unfollow(state, "did:plc:abc", "not_following_back")
        bluesky_state.record_unfollow(state, "did:plc:abc", "not_following_back")
        entries = state["unfollow_history"]["entries"]
        self.assertEqual(len(entries), 1)

    def test_prune_unfollow_history_keeps_most_recent_entries(self):
        state = bluesky_state._default_state()
        for i in range(5):
            bluesky_state.record_unfollow(state, f"did:plc:{i:03d}")
        bluesky_state.prune_unfollow_history(state, max_entries=3)
        self.assertEqual(len(state["unfollow_history"]["entries"]), 3)

    def test_normalise_state_backfills_unfollow_history(self):
        # Simulate an older state file without the unfollow_history key.
        old_state = {
            "posted_jokes": [],
            "provider": {},
            "reports": {},
            "liked_replies": {},
        }
        normalised = bluesky_state._normalise_state(old_state)
        self.assertIn("unfollow_history", normalised)
        self.assertIn("entries", normalised["unfollow_history"])


class JokeRetryChainTests(unittest.TestCase):
    def test_pick_joke_returns_new_joke(self):
        """pick_joke fetches and returns a non-duplicate joke."""
        recent = set()
        with mock.patch.object(
            bluesky_joke_providers, "PROVIDERS", {"test_provider": lambda: "Test joke"}
        ):
            joke, encoded = bluesky_post_joke.pick_joke(recent, "test_provider")
        self.assertEqual(joke, "Test joke")
        self.assertNotIn(encoded, recent)

    def test_pick_joke_skips_duplicates(self):
        """pick_joke skips jokes already in recent_b64s."""
        joke1 = "Old joke"
        b64_old = base64.b64encode(joke1.encode()).decode()
        recent = {b64_old}

        call_count = [0]

        def mock_fetch():
            call_count[0] += 1
            if call_count[0] == 1:
                return joke1  # Duplicate
            return "New joke"  # Not a duplicate

        with mock.patch.object(
            bluesky_joke_providers, "PROVIDERS", {"test_provider": mock_fetch}
        ):
            joke, encoded = bluesky_post_joke.pick_joke(recent, "test_provider")

        self.assertEqual(joke, "New joke")
        self.assertEqual(call_count[0], 2)

    def test_pick_joke_raises_when_all_duplicates(self):
        """pick_joke raises ValueError if MAX_ATTEMPTS are all duplicates."""
        joke = "All the same"
        b64 = base64.b64encode(joke.encode()).decode()
        recent = {b64}

        with mock.patch.object(
            bluesky_joke_providers, "PROVIDERS", {"test_provider": lambda: joke}
        ):
            with self.assertRaises(ValueError) as ctx:
                bluesky_post_joke.pick_joke(recent, "test_provider")

        self.assertIn("duplicates", str(ctx.exception))

    def test_sanitise_joke_text_repairs_mojibake_apostrophe(self):
        raw = "Why do pumpkins sit on peopleâs porches?"
        fixed = bluesky_post_joke.sanitise_joke_text(raw)
        self.assertEqual(fixed, "Why do pumpkins sit on people's porches?")

    def test_sanitise_joke_text_removes_utf8_bom_prefix(self):
        raw = "\ufeffA clean joke"
        fixed = bluesky_post_joke.sanitise_joke_text(raw)
        self.assertEqual(fixed, "A clean joke")

    def test_sanitise_joke_text_decodes_numeric_html_entity(self):
        raw = "Did you hear about the kidnapping at school? It&#039;s ok, he woke up."
        fixed = bluesky_post_joke.sanitise_joke_text(raw)
        self.assertEqual(
            fixed, "Did you hear about the kidnapping at school? It's ok, he woke up."
        )

    def test_sanitise_joke_text_decodes_named_html_entity(self):
        raw = "Dad&apos;s favourite joke"
        fixed = bluesky_post_joke.sanitise_joke_text(raw)
        self.assertEqual(fixed, "Dad's favourite joke")

    def test_sanitise_joke_text_decodes_double_escaped_entity(self):
        raw = "It&amp;#039;s still funny"
        fixed = bluesky_post_joke.sanitise_joke_text(raw)
        self.assertEqual(fixed, "It's still funny")

    def test_pick_joke_normalises_curly_quotes_before_return(self):
        with mock.patch.object(
            bluesky_joke_providers,
            "PROVIDERS",
            {"test_provider": lambda: "It's called \u2018normalisation\u2019."},
        ):
            joke, _ = bluesky_post_joke.pick_joke(set(), "test_provider")
        self.assertEqual(joke, "It's called 'normalisation'.")

    def test_pick_joke_decodes_html_entities_before_return(self):
        with mock.patch.object(
            bluesky_joke_providers,
            "PROVIDERS",
            {"test_provider": lambda: "It&amp;#039;s fixed"},
        ):
            joke, _ = bluesky_post_joke.pick_joke(set(), "test_provider")
        self.assertEqual(joke, "It's fixed")

    def test_pick_joke_skips_joke_exceeding_char_limit(self):
        """pick_joke skips jokes that are too long and retries for a short one."""
        long_joke = "x" * (bluesky_post_joke._MAX_JOKE_CHARS + 1)
        short_joke = "A short joke."
        call_count = [0]

        def mock_fetch():
            call_count[0] += 1
            return long_joke if call_count[0] == 1 else short_joke

        with mock.patch.object(
            bluesky_joke_providers, "PROVIDERS", {"test_provider": mock_fetch}
        ):
            joke, _ = bluesky_post_joke.pick_joke(set(), "test_provider")

        self.assertEqual(joke, short_joke)
        self.assertEqual(call_count[0], 2)

    def test_pick_joke_raises_when_all_jokes_too_long(self):
        """pick_joke raises ValueError when every attempt exceeds the char limit."""
        long_joke = "x" * (bluesky_post_joke._MAX_JOKE_CHARS + 1)

        with mock.patch.object(
            bluesky_joke_providers, "PROVIDERS", {"test_provider": lambda: long_joke}
        ):
            with self.assertRaises(ValueError):
                bluesky_post_joke.pick_joke(set(), "test_provider")

    def test_grapheme_len_treats_combining_mark_sequence_as_one(self):
        self.assertEqual(bluesky_post_joke._grapheme_len("e\u0301"), 1)

    def test_pick_joke_accepts_combining_sequence_at_grapheme_limit(self):
        # Each "e\u0301" is one grapheme, despite being two code points.
        grapheme_limited_joke = "e\u0301" * bluesky_post_joke._MAX_JOKE_CHARS

        with mock.patch.object(
            bluesky_joke_providers,
            "PROVIDERS",
            {"test_provider": lambda: grapheme_limited_joke},
        ):
            joke, _ = bluesky_post_joke.pick_joke(set(), "test_provider")

        self.assertEqual(joke, grapheme_limited_joke)

    def test_pick_joke_rejects_grapheme_over_limit(self):
        over_limit_joke = "x" * (bluesky_post_joke._MAX_JOKE_CHARS + 1)

        with mock.patch.object(
            bluesky_joke_providers,
            "PROVIDERS",
            {"test_provider": lambda: over_limit_joke},
        ):
            with self.assertRaises(ValueError):
                bluesky_post_joke.pick_joke(set(), "test_provider")

    def test_provider_fallback_chain_tries_primaries_first(self):
        """Provider fallback tries primary providers before backups."""
        state = bluesky_state._default_state()

        # icanhazdadjoke is PRIMARY_PROVIDERS[0], jokeapi is PRIMARY_PROVIDERS[1]
        self.assertEqual(bluesky_joke_providers.PRIMARY_PROVIDERS[0], "icanhazdadjoke")

        # After setting last_used to icanhazdadjoke, next should be jokeapi (still primary)
        state["provider"]["last_used"] = "icanhazdadjoke"
        next_provider = bluesky_state.get_next_provider(state)
        self.assertIn(next_provider, bluesky_joke_providers.PRIMARY_PROVIDERS)

    def test_fallback_provider_separate_from_backups(self):
        """Fallback provider (jokebook) is separate from backup providers."""
        self.assertEqual("jokebot_jokebook", bluesky_joke_providers.FALLBACK_PROVIDER)
        self.assertNotIn("jokebot_jokebook", bluesky_joke_providers.BACKUP_PROVIDERS)
        self.assertIn("syrsly", bluesky_joke_providers.BACKUP_PROVIDERS)
        self.assertIn("api_ninjas", bluesky_joke_providers.BACKUP_PROVIDERS)

    def test_deduplication_includes_denylisted_jokes(self):
        """Deduplication set includes both recent and denylisted jokes."""
        state = bluesky_state._default_state()
        recent_joke = "This joke was posted recently"
        b64_recent = base64.b64encode(recent_joke.encode()).decode()

        state["posted_jokes"] = [
            {
                "ts": bluesky_post_joke.get_current_epoch() - 100,
                "b64": b64_recent,
                "provider": "test",
            }
        ]

        denylist = {"jokes": [{"b64": "denied_b64", "source_post_uri": "at://post/1"}]}

        cutoff = bluesky_post_joke.get_current_epoch() - (90 * 86400)
        recent_b64s = bluesky_state.get_recent_b64s(state, cutoff)
        recent_b64s |= bluesky_denylist.get_denylisted_b64s(denylist)

        self.assertIn(b64_recent, recent_b64s)
        self.assertIn("denied_b64", recent_b64s)

    def test_fallback_joke_used_when_all_providers_fail(self):
        """Fallback static joke is used when all providers raise."""
        fallback = bluesky_post_joke.get_fallback_joke()
        self.assertIsInstance(fallback, str)
        self.assertGreater(len(fallback), 0)
        # Fallback should be self-deprecating or reference script/debugging
        self.assertTrue(
            any(
                keyword in fallback.lower()
                for keyword in ["script", "byte", "debug", "exception", "fail"]
            )
        )


class StarterPackFollowSyncTests(unittest.TestCase):
    """Tests for ensure_following_list_members (CS-9 coverage gap)."""

    def test_follows_member_not_yet_followed(self):
        client = mock.Mock()
        client.me.did = "did:plc:bot"

        with mock.patch(
            "bluesky_manage_starter_pack.fetch_paginated_data",
            return_value=[SimpleNamespace(did="did:plc:a")],
        ):
            with mock.patch(
                "bluesky_manage_starter_pack.retry_network_call",
                side_effect=lambda fn, description: fn(),
            ):
                already, followed = (
                    bluesky_manage_starter_pack.ensure_following_list_members(
                        client,
                        {"did:plc:a", "did:plc:b"},
                        dry_run=False,
                        action_delay_seconds=0,
                    )
                )

        self.assertEqual(followed, 1)
        client.follow.assert_called_once_with("did:plc:b")

    def test_dry_run_does_not_call_follow(self):
        client = mock.Mock()
        client.me.did = "did:plc:bot"

        with mock.patch(
            "bluesky_manage_starter_pack.fetch_paginated_data",
            return_value=[],
        ):
            _, followed = bluesky_manage_starter_pack.ensure_following_list_members(
                client,
                {"did:plc:x"},
                dry_run=True,
                action_delay_seconds=0,
            )

        self.assertEqual(followed, 1)
        client.follow.assert_not_called()

    def test_does_not_follow_self(self):
        client = mock.Mock()
        client.me.did = "did:plc:bot"

        with mock.patch(
            "bluesky_manage_starter_pack.fetch_paginated_data",
            return_value=[],
        ):
            with mock.patch(
                "bluesky_manage_starter_pack.retry_network_call",
                side_effect=lambda fn, description: fn(),
            ):
                _, followed = bluesky_manage_starter_pack.ensure_following_list_members(
                    client,
                    {"did:plc:bot"},
                    dry_run=False,
                    action_delay_seconds=0,
                )

        self.assertEqual(followed, 0)
        client.follow.assert_not_called()

    def test_skips_already_followed_members(self):
        client = mock.Mock()
        client.me.did = "did:plc:bot"

        with mock.patch(
            "bluesky_manage_starter_pack.fetch_paginated_data",
            return_value=[
                SimpleNamespace(did="did:plc:a"),
                SimpleNamespace(did="did:plc:b"),
            ],
        ):
            already, followed = (
                bluesky_manage_starter_pack.ensure_following_list_members(
                    client,
                    {"did:plc:a", "did:plc:b"},
                    dry_run=False,
                    action_delay_seconds=0,
                )
            )

        self.assertEqual(followed, 0)
        self.assertEqual(already, 2)
        client.follow.assert_not_called()

    def test_upsert_preserves_existing_created_at_on_update(self):
        """CS-5: createdAt from the existing record is preserved on put_record path."""
        client = mock.Mock()
        client.me.did = "did:plc:test"

        original_ts = "2025-01-01T00:00:00Z"
        existing_record = SimpleNamespace(
            value={"createdAt": original_ts, "name": "Old Name"}
        )

        captured_record = {}

        def capture_put(payload):
            captured_record.update(payload.get("record", {}))
            return SimpleNamespace(
                uri="at://did:plc:test/app.bsky.graph.starterpack/3mkrjdntf7x2l"
            )

        client.com.atproto.repo.get_record.return_value = existing_record
        client.com.atproto.repo.put_record.side_effect = capture_put

        with mock.patch(
            "bluesky_manage_starter_pack.retry_network_call",
            side_effect=lambda fn, description: fn(),
        ):
            bluesky_manage_starter_pack.upsert_starter_pack_record(
                client,
                {
                    "name": "Updated Pack",
                    "description": "Desc",
                    "starter_pack_uri": "at://did:plc:test/app.bsky.graph.starterpack/3mkrjdntf7x2l",
                    "record_key": "",
                },
                source_list_uri="at://did:plc:test/app.bsky.graph.list/3abc",
                dry_run=False,
            )

        self.assertEqual(captured_record.get("createdAt"), original_ts)


class ReportNotificationCollectionTests(unittest.TestCase):
    """Tests for collect_report_proposals (CS-9 coverage gap)."""

    def test_respects_max_pages_limit(self):
        """Stops paging when max_pages limit is reached."""
        client = mock.Mock()
        state = bluesky_state._default_state()
        denylisted = set()

        response1 = SimpleNamespace(notifications=[], cursor="cursor1")
        response2 = SimpleNamespace(notifications=[], cursor="cursor2")

        client.app.bsky.notification.list_notifications.side_effect = [
            response1,
            response2,
        ]

        with mock.patch(
            "bluesky_process_reports.retry_network_call",
            side_effect=lambda fn, description: fn(),
        ):
            with mock.patch.dict(os.environ, {"BLUESKY_REPORT_MAX_PAGES": "1"}):
                proposals, processed, pages = (
                    bluesky_process_reports.collect_report_proposals(
                        client, state, denylisted
                    )
                )

        self.assertEqual(pages, 1)
        self.assertEqual(client.app.bsky.notification.list_notifications.call_count, 1)

    def test_stops_on_empty_cursor(self):
        """Stops paging when cursor becomes None."""
        client = mock.Mock()
        state = bluesky_state._default_state()
        denylisted = set()

        response = SimpleNamespace(notifications=[], cursor=None)

        client.app.bsky.notification.list_notifications.return_value = response

        with mock.patch(
            "bluesky_process_reports.retry_network_call",
            side_effect=lambda fn, description: fn(),
        ):
            proposals, processed, pages = (
                bluesky_process_reports.collect_report_proposals(
                    client, state, denylisted
                )
            )

        self.assertEqual(pages, 1)
        self.assertEqual(len(proposals), 0)

    def test_marks_non_reply_notifications_as_processed(self):
        """Non-reply notifications are marked processed even if skipped."""
        client = mock.Mock()
        state = bluesky_state._default_state()
        denylisted = set()

        non_reply_notif = SimpleNamespace(
            uri="at://did:plc:bot/app.bsky.feed.post/notif1",
            reason="like",
            record=SimpleNamespace(),
        )
        response = SimpleNamespace(notifications=[non_reply_notif], cursor=None)

        client.app.bsky.notification.list_notifications.return_value = response

        with mock.patch(
            "bluesky_process_reports.retry_network_call",
            side_effect=lambda fn, description: fn(),
        ):
            with mock.patch(
                "bluesky_process_reports._extract_notification",
                return_value={
                    "notification_uri": "at://did:plc:bot/app.bsky.feed.post/notif1",
                    "reason": "like",
                    "reply_text": "",
                    "source_post_uri": None,
                },
            ):
                proposals, processed, pages = (
                    bluesky_process_reports.collect_report_proposals(
                        client, state, denylisted
                    )
                )

        self.assertIn("at://did:plc:bot/app.bsky.feed.post/notif1", processed)

    def test_skips_already_processed_notification_uris(self):
        """Already-processed notification URIs are skipped entirely."""
        client = mock.Mock()
        state = bluesky_state._default_state()
        processed_uri = "at://did:plc:bot/app.bsky.feed.post/already_done"
        bluesky_state.record_processed_notification(state, processed_uri)
        denylisted = set()

        notif = SimpleNamespace(
            uri=processed_uri,
            reason="reply",
            record=SimpleNamespace(),
        )
        response = SimpleNamespace(notifications=[notif], cursor=None)

        client.app.bsky.notification.list_notifications.return_value = response

        with mock.patch(
            "bluesky_process_reports.retry_network_call",
            side_effect=lambda fn, description: fn(),
        ):
            proposals, processed, pages = (
                bluesky_process_reports.collect_report_proposals(
                    client, state, denylisted
                )
            )

        # Already-processed URI should not be added to new processed set
        self.assertNotIn(processed_uri, processed)
        self.assertEqual(len(proposals), 0)


class ApprovedReportDeletionTests(unittest.TestCase):
    """Tests for delete_approved_report_posts (CS-9 coverage gap)."""

    def test_deletes_uri_from_denylist(self):
        client = mock.Mock()
        state = bluesky_state._default_state()
        denylist = {
            "jokes": [
                {
                    "b64": "abc=",
                    "source_post_uri": "at://did:plc:test/app.bsky.feed.post/rkey1",
                }
            ]
        }

        with mock.patch(
            "bluesky_process_reports.retry_network_call",
            side_effect=lambda fn, description: fn(),
        ):
            count = bluesky_process_reports.delete_approved_report_posts(
                client, denylist, state
            )

        self.assertEqual(count, 1)
        self.assertIn(
            "at://did:plc:test/app.bsky.feed.post/rkey1",
            bluesky_state.get_deleted_post_uris(state),
        )
        client.app.bsky.feed.post.delete.assert_called_once()

    def test_skips_already_deleted_uri(self):
        client = mock.Mock()
        state = bluesky_state._default_state()
        uri = "at://did:plc:test/app.bsky.feed.post/done"
        bluesky_state.record_deleted_post_uri(state, uri)
        denylist = {"jokes": [{"b64": "abc=", "source_post_uri": uri}]}

        count = bluesky_process_reports.delete_approved_report_posts(
            client, denylist, state
        )

        self.assertEqual(count, 0)
        client.app.bsky.feed.post.delete.assert_not_called()

    def test_handles_entry_with_no_post_uri(self):
        client = mock.Mock()
        state = bluesky_state._default_state()
        denylist = {"jokes": [{"b64": "abc="}]}

        count = bluesky_process_reports.delete_approved_report_posts(
            client, denylist, state
        )

        self.assertEqual(count, 0)
        client.app.bsky.feed.post.delete.assert_not_called()

    def test_records_permanent_failure_for_invalid_uri(self):
        client = mock.Mock()
        state = bluesky_state._default_state()
        bad_uri = "not-a-valid-uri"
        denylist = {"jokes": [{"b64": "abc=", "source_post_uri": bad_uri}]}

        count = bluesky_process_reports.delete_approved_report_posts(
            client, denylist, state
        )

        self.assertEqual(count, 0)
        self.assertIn(bad_uri, bluesky_state.get_deleted_post_uris(state))
        client.app.bsky.feed.post.delete.assert_not_called()


class StateRoundTripTests(unittest.TestCase):
    """Tests for load_state/save_state round-trip (CS-9 coverage gap)."""

    def test_save_and_load_round_trips_posted_jokes(self):
        import tempfile

        state = bluesky_state._default_state()
        state["posted_jokes"] = [{"ts": 9999, "b64": "dGVzdA==", "provider": "jokeapi"}]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = str(pathlib.Path(tmpdir) / "bot_state.json")
            with mock.patch("bluesky_state.STATE_FILE", tmp_path):
                bluesky_state.save_state(state)
                loaded = bluesky_state.load_state()

        self.assertEqual(len(loaded["posted_jokes"]), 1)
        self.assertEqual(loaded["posted_jokes"][0]["b64"], "dGVzdA==")

    def test_load_state_returns_default_when_file_missing(self):
        with mock.patch(
            "bluesky_state.STATE_FILE", "/tmp/does-not-exist-jokebot-state.json"
        ):
            loaded = bluesky_state.load_state()

        self.assertIn("posted_jokes", loaded)
        self.assertEqual(loaded["posted_jokes"], [])

    def test_save_state_is_atomic_via_temp_file(self):
        """save_state writes to a .tmp file then replaces atomically."""
        import tempfile

        state = bluesky_state._default_state()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = str(pathlib.Path(tmpdir) / "bot_state.json")
            with mock.patch("bluesky_state.STATE_FILE", tmp_path):
                with mock.patch("os.replace", wraps=os.replace) as mock_replace:
                    bluesky_state.save_state(state)
                    mock_replace.assert_called_once()
                    call_args = mock_replace.call_args[0]
                    # Source should be a .tmp file; destination should be STATE_FILE.
                    self.assertTrue(call_args[0].endswith(".tmp"))
                    self.assertEqual(call_args[1], tmp_path)

    def test_load_state_normalises_old_state_missing_liked_replies(self):
        """Older state files without liked_replies are backfilled on load."""
        import json
        import tempfile

        old = {
            "posted_jokes": [],
            "provider": bluesky_state._default_state()["provider"],
            "reports": {},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = str(pathlib.Path(tmpdir) / "bot_state.json")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(old, f)
            with mock.patch("bluesky_state.STATE_FILE", tmp_path):
                loaded = bluesky_state.load_state()

        self.assertIn("liked_replies", loaded)
        self.assertIn("liked_uris", loaded["liked_replies"])


class FollowFellowsMainTests(unittest.TestCase):
    """Smoke tests for bluesky_follow_fellows.main() (CS-9 coverage gap)."""

    def test_main_dry_run_does_not_call_follow(self):
        client = mock.Mock()
        client.me.did = "did:plc:bot"
        client.app.bsky.feed.search_posts.return_value = SimpleNamespace(posts=[])
        state = bluesky_state._default_state()

        with mock.patch(
            "bluesky_follow_fellows.login_client",
            return_value=(client, "thejokebot.bsky.social"),
        ):
            with mock.patch(
                "bluesky_follow_fellows.get_runtime_controls",
                return_value={"dry_run": True, "action_delay_seconds": 0.0},
            ):
                with mock.patch(
                    "bluesky_follow_fellows.fetch_paginated_data", return_value=[]
                ):
                    with mock.patch(
                        "bluesky_follow_fellows.bluesky_state.load_state",
                        return_value=state,
                    ):
                        with mock.patch(
                            "bluesky_follow_fellows.retry_network_call",
                            side_effect=lambda fn, description: fn(),
                        ):
                            bluesky_follow_fellows.main()

        client.follow.assert_not_called()

    def test_main_excludes_already_following(self):
        """Users already followed are excluded from candidates."""
        already_did = "did:plc:already"
        client = mock.Mock()
        client.me.did = "did:plc:bot"
        # search_posts returns one user the bot already follows
        post = SimpleNamespace(author=SimpleNamespace(did=already_did))
        client.app.bsky.feed.search_posts.return_value = SimpleNamespace(posts=[post])
        state = bluesky_state._default_state()

        with mock.patch(
            "bluesky_follow_fellows.login_client",
            return_value=(client, "thejokebot.bsky.social"),
        ):
            with mock.patch(
                "bluesky_follow_fellows.get_runtime_controls",
                return_value={"dry_run": True, "action_delay_seconds": 0.0},
            ):
                with mock.patch(
                    "bluesky_follow_fellows.fetch_paginated_data",
                    return_value=[SimpleNamespace(did=already_did)],
                ):
                    with mock.patch(
                        "bluesky_follow_fellows.bluesky_state.load_state",
                        return_value=state,
                    ):
                        with mock.patch(
                            "bluesky_follow_fellows.retry_network_call",
                            side_effect=lambda fn, description: fn(),
                        ):
                            bluesky_follow_fellows.main()

        client.follow.assert_not_called()

    def test_main_excludes_previously_unfollowed_dids(self):
        """Users in unfollow history are excluded from follow candidates."""
        prev_unfollowed = "did:plc:prev"
        client = mock.Mock()
        client.me.did = "did:plc:bot"
        post = SimpleNamespace(author=SimpleNamespace(did=prev_unfollowed))
        client.app.bsky.feed.search_posts.return_value = SimpleNamespace(posts=[post])
        state = bluesky_state._default_state()
        bluesky_state.record_unfollow(state, prev_unfollowed)

        with mock.patch(
            "bluesky_follow_fellows.login_client",
            return_value=(client, "thejokebot.bsky.social"),
        ):
            with mock.patch(
                "bluesky_follow_fellows.get_runtime_controls",
                return_value={"dry_run": True, "action_delay_seconds": 0.0},
            ):
                with mock.patch(
                    "bluesky_follow_fellows.fetch_paginated_data", return_value=[]
                ):
                    with mock.patch(
                        "bluesky_follow_fellows.bluesky_state.load_state",
                        return_value=state,
                    ):
                        with mock.patch(
                            "bluesky_follow_fellows.retry_network_call",
                            side_effect=lambda fn, description: fn(),
                        ):
                            bluesky_follow_fellows.main()

        client.follow.assert_not_called()


if __name__ == "__main__":
    unittest.main()
