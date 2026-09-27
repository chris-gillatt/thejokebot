import datetime as dt
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import atproto_client.exceptions
import requests

from scripts import update_provider_health
from thejokebot import denylist
from thejokebot.commands import create_report_prs
from thejokebot.commands import follows_and_likes
from thejokebot.commands import manage_starter_pack
from thejokebot.commands import process_reports
from thejokebot.commands import unfollow
from thejokebot.commands import validate_runtime_config
from thejokebot.commands import validate_unfollow_ignore
from thejokebot.commands import verify_latest_joke_post


class DenylistCoverageTests(unittest.TestCase):
    def test_load_save_and_fallback_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "denylist.json"
            self.assertEqual(denylist.load_denylist(path), {"version": 1, "jokes": []})

            denylist.save_denylist({"jokes": [{"b64": "one"}]}, path)
            self.assertEqual(denylist.load_denylist(path)["jokes"][0]["b64"], "one")

            path.write_text("[]", encoding="utf-8")
            self.assertEqual(denylist.load_denylist(path), {"version": 1, "jokes": []})

            path.write_text('{"jokes": []}', encoding="utf-8")
            self.assertEqual(denylist.load_denylist(path)["version"], 1)


class IgnoreValidationCoverageTests(unittest.TestCase):
    def test_resolve_handles_classifies_all_outcomes(self):
        client = mock.Mock()
        stale_error = atproto_client.exceptions.BadRequestError()
        stale_error.args = ("profile not found",)
        transient_error = atproto_client.exceptions.BadRequestError()
        transient_error.args = ("service rejected request",)
        client.get_profile.side_effect = [
            SimpleNamespace(did="did:plc:valid"),
            {},
            stale_error,
            transient_error,
            requests.RequestException("offline"),
        ]

        with mock.patch.object(
            validate_unfollow_ignore,
            "retry_network_call",
            side_effect=lambda fn, description: fn(),
        ):
            valid, stale, transient = validate_unfollow_ignore.resolve_handles(
                client, ["valid", "empty", "stale", "bad", "offline"]
            )

        self.assertEqual(valid, {"valid": "did:plc:valid"})
        self.assertEqual(set(stale), {"empty", "stale"})
        self.assertEqual(set(transient), {"bad", "offline"})

    def test_main_reports_results_and_fails_only_for_enforced_stale_entries(self):
        outcomes = (
            (True, 1),
            (False, 0),
        )
        for fail_on_stale, expected in outcomes:
            with (
                self.subTest(fail_on_stale=fail_on_stale),
                mock.patch.object(
                    validate_unfollow_ignore, "get_bool_env", return_value=fail_on_stale
                ),
                mock.patch.object(
                    validate_unfollow_ignore,
                    "parse_ignore_handles",
                    return_value=["valid", "stale", "transient"],
                ),
                mock.patch.object(
                    validate_unfollow_ignore,
                    "login_client",
                    return_value=(mock.Mock(), "bot"),
                ),
                mock.patch.object(
                    validate_unfollow_ignore,
                    "resolve_handles",
                    return_value=(
                        {"valid": "did:plc:valid"},
                        {"stale": "not found"},
                        {"transient": "offline"},
                    ),
                ),
            ):
                self.assertEqual(validate_unfollow_ignore.main(), expected)


class LatestPostCoverageTests(unittest.TestCase):
    @staticmethod
    def _item(*, did="did:plc:bot", text="Joke #dadjoke", created_at=None):
        created_at = created_at or dt.datetime.now(dt.timezone.utc).isoformat()
        return SimpleNamespace(
            post=SimpleNamespace(
                author=SimpleNamespace(did=did),
                record=SimpleNamespace(text=text, created_at=created_at),
                uri="at://did:plc:bot/app.bsky.feed.post/abc",
            )
        )

    def test_parse_helpers_reject_invalid_values(self):
        self.assertIsNone(verify_latest_joke_post.parse_created_at(None))
        self.assertIsNone(verify_latest_joke_post.parse_created_at("invalid"))
        naive = verify_latest_joke_post.parse_created_at("2026-01-01T00:00:00")
        assert naive is not None
        self.assertEqual(naive.tzinfo, dt.timezone.utc)
        self.assertEqual(verify_latest_joke_post.extract_text(object()), "")
        self.assertIsNone(verify_latest_joke_post.to_post_url("bot", ""))
        self.assertIsNone(verify_latest_joke_post.to_post_url("bot", "at://"))

    def test_main_finds_recent_post_and_skips_irrelevant_items(self):
        client = mock.Mock(me=SimpleNamespace(did="did:plc:bot"))
        client.get_author_feed.return_value = SimpleNamespace(
            feed=[
                self._item(did="did:plc:other"),
                object(),
                self._item(text="No tag"),
                self._item(created_at="invalid"),
                self._item(text="A sufficiently recent joke #dadjoke"),
            ]
        )
        with (
            mock.patch.object(
                verify_latest_joke_post,
                "parse_args",
                return_value=SimpleNamespace(max_age_hours=24, limit=25),
            ),
            mock.patch.object(
                verify_latest_joke_post,
                "login_client",
                return_value=(client, "bot.test"),
            ),
        ):
            self.assertEqual(verify_latest_joke_post.main(), 0)

    def test_main_fails_without_recent_match(self):
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat()
        client = mock.Mock(me=SimpleNamespace(did="did:plc:bot"))
        client.get_author_feed.return_value = SimpleNamespace(
            feed=[self._item(created_at=old)]
        )
        with (
            mock.patch.object(
                verify_latest_joke_post,
                "parse_args",
                return_value=SimpleNamespace(max_age_hours=24, limit=25),
            ),
            mock.patch.object(
                verify_latest_joke_post,
                "login_client",
                return_value=(client, "bot.test"),
            ),
        ):
            self.assertEqual(verify_latest_joke_post.main(), 1)


class RuntimeConfigCoverageTests(unittest.TestCase):
    def test_extract_cron_handles_io_and_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.yml"
            self.assertIsNone(validate_runtime_config._extract_cron(path))
            path.write_text('on:\n  schedule:\n    - cron: "1 2 * * *" # note\n')
            self.assertEqual(validate_runtime_config._extract_cron(path), "1 2 * * *")

        with mock.patch.object(
            validate_runtime_config,
            "_extract_cron",
            side_effect=[None, "3 4 * * *"],
        ) as extract:
            cron, resolved = validate_runtime_config._extract_cron_with_fallback(
                ".github/workflows/example.yml"
            )
        self.assertEqual(cron, "3 4 * * *")
        self.assertEqual(resolved, ".github/workflows-disabled/example.yml")
        self.assertEqual(extract.call_count, 2)

    def test_validate_reports_load_shape_missing_and_mismatched_schedules(self):
        with mock.patch.object(
            validate_runtime_config.runtime_config,
            "load_runtime_config",
            side_effect=ValueError("invalid"),
        ):
            self.assertEqual(
                validate_runtime_config.validate_runtime_config(), ["invalid"]
            )

        with mock.patch.object(
            validate_runtime_config.runtime_config,
            "load_runtime_config",
            return_value={"workflow_schedules": []},
        ):
            self.assertEqual(
                validate_runtime_config.validate_runtime_config(),
                ["workflow_schedules must be an object in runtime config."],
            )

        schedules = {
            key: "configured" for key in validate_runtime_config.WORKFLOW_FILES
        }
        schedules.pop(next(iter(schedules)))
        with (
            mock.patch.object(
                validate_runtime_config.runtime_config,
                "load_runtime_config",
                return_value={"workflow_schedules": schedules},
            ),
            mock.patch.object(
                validate_runtime_config,
                "_extract_cron_with_fallback",
                side_effect=[(None, "missing"), *[("actual", "path")] * 5],
            ),
            mock.patch.object(
                validate_runtime_config, "_validate_guard_rails", return_value=[]
            ),
        ):
            errors = validate_runtime_config.validate_runtime_config()
        self.assertTrue(any("Missing workflow_schedules" in error for error in errors))
        self.assertTrue(any("Could not read cron" in error for error in errors))
        self.assertTrue(any("Schedule mismatch" in error for error in errors))

    def test_main_success_and_failure(self):
        with mock.patch.object(
            validate_runtime_config, "validate_runtime_config", return_value=[]
        ):
            self.assertEqual(validate_runtime_config.main(), 0)
        with mock.patch.object(
            validate_runtime_config, "validate_runtime_config", return_value=["bad"]
        ):
            self.assertEqual(validate_runtime_config.main(), 1)


class ProviderHealthMainCoverageTests(unittest.TestCase):
    def test_main_success_and_critical_failure(self):
        healthy = {
            "success": True,
            "configured": True,
            "error": None,
            "check_at": 1,
        }
        for critical, expected_exit in (([], 0), ([("jokeapi", 2)], 1)):
            with (
                self.subTest(critical=critical),
                mock.patch.object(
                    update_provider_health,
                    "check_provider_health",
                    return_value=healthy,
                ),
                mock.patch.object(
                    update_provider_health.bot_state,
                    "update_state",
                    return_value={},
                ),
                mock.patch.object(
                    update_provider_health, "_critical_failures", return_value=critical
                ),
                self.assertRaises(SystemExit) as raised,
            ):
                update_provider_health.main()
            self.assertEqual(raised.exception.code, expected_exit)


class ReportCommandCoverageTests(unittest.TestCase):
    def test_report_text_mapping_helpers_cover_decode_thread_and_encoding(self):
        encoded = "SGVsbG8="
        self.assertEqual(process_reports._decode_joke_preview(encoded), "Hello")
        self.assertEqual(
            process_reports._decode_joke_preview(encoded, max_chars=4), "H..."
        )
        self.assertEqual(
            process_reports._decode_joke_preview("not-base64"),
            "<unable to decode joke text>",
        )
        self.assertIsNone(process_reports._encode_text_b64(None))
        self.assertEqual(process_reports._encode_text_b64("Hello"), encoded)

        client = mock.Mock()
        client.get_post_thread.return_value = SimpleNamespace(
            thread=SimpleNamespace(
                post=SimpleNamespace(
                    record=SimpleNamespace(text="Hello\n\n#dadjoke #funny")
                )
            )
        )
        self.assertEqual(
            process_reports._extract_thread_post_text(client, "at://post"), "Hello"
        )
        client.get_post_thread.side_effect = ValueError("bad")
        self.assertIsNone(
            process_reports._extract_thread_post_text(client, "at://post")
        )

    def test_delete_and_acknowledge_classify_transient_and_permanent_errors(self):
        client = mock.Mock()
        self.assertEqual(
            process_reports._delete_post(client, "invalid"), (False, False)
        )
        for error, expected in (
            (requests.RequestException("offline"), (False, True)),
            (ValueError("invalid"), (False, False)),
        ):
            with (
                self.subTest(error=error),
                mock.patch.object(
                    process_reports, "retry_network_call", side_effect=error
                ),
            ):
                self.assertEqual(
                    process_reports._delete_post(
                        client, "at://did:plc:test/app.bsky.feed.post/key"
                    ),
                    expected,
                )

        proposal = {
            "source_reply_uri": "at://reply",
            "reply_cid": "reply-cid",
            "root_uri": "at://root",
            "root_cid": "root-cid",
        }
        for error, expected in (
            (requests.RequestException("offline"), (False, True)),
            (ValueError("invalid"), (False, False)),
        ):
            with (
                self.subTest(error=error),
                mock.patch.object(
                    process_reports, "retry_network_call", side_effect=error
                ),
            ):
                self.assertEqual(
                    process_reports.acknowledge_report(client, proposal), expected
                )

    def test_resolve_notification_proposal_filters_and_builds_fallback(self):
        base = {
            "reason": "reply",
            "reply_text": "#report",
            "source_post_uri": "at://post",
            "reply_uri": "at://reply",
            "reply_cid": "reply-cid",
            "root_uri": None,
            "root_cid": "root-cid",
            "author_did": "did:reporter",
            "indexed_at": "now",
        }
        client = mock.Mock()
        for changes in (
            {"reason": "like"},
            {"reply_text": "hello"},
            {"source_post_uri": None},
        ):
            parsed = {**base, **changes}
            self.assertEqual(
                process_reports._resolve_notification_proposal(
                    parsed, {}, set(), set(), client
                ),
                (None, True),
            )

        with mock.patch.object(
            process_reports, "_extract_thread_post_text", return_value=None
        ):
            self.assertEqual(
                process_reports._resolve_notification_proposal(
                    base, {}, set(), set(), client
                ),
                (None, False),
            )

        encoded = process_reports._encode_text_b64("Joke")
        with mock.patch.object(
            process_reports, "_extract_thread_post_text", return_value="Joke"
        ):
            self.assertEqual(
                process_reports._resolve_notification_proposal(
                    base, {}, {encoded}, set(), client
                ),
                (None, True),
            )
            proposal, should_mark = process_reports._resolve_notification_proposal(
                base, {}, set(), set(), client
            )
        self.assertTrue(should_mark)
        assert proposal is not None
        self.assertEqual(proposal["b64"], encoded)
        self.assertEqual(proposal["source_provider"], "unknown")

    def test_collect_report_proposals_handles_network_error_and_adds_proposal(self):
        state = bot_state = {"reports": {}, "posted_jokes": []}
        with mock.patch.object(
            process_reports,
            "retry_network_call",
            side_effect=requests.RequestException("offline"),
        ):
            proposals, processed, pages = process_reports.collect_report_proposals(
                mock.Mock(), state, set()
            )
        self.assertEqual((proposals, processed, pages), ([], set(), 0))

        response = SimpleNamespace(notifications=[object()], cursor=None)
        with (
            mock.patch.object(
                process_reports, "retry_network_call", return_value=response
            ),
            mock.patch.object(
                process_reports,
                "_process_report_notification",
                return_value={"b64": "encoded"},
            ),
        ):
            proposals, _processed, pages = process_reports.collect_report_proposals(
                mock.Mock(), bot_state, set()
            )
        self.assertEqual(proposals, [{"b64": "encoded"}])
        self.assertEqual(pages, 1)

    def test_create_report_pr_main_handles_missing_empty_and_created(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proposals.json"
            with mock.patch.dict("os.environ", {"BLUESKY_REPORT_OUTPUT": str(path)}):
                create_report_prs.main()

            path.write_text('{"proposals": []}', encoding="utf-8")
            with mock.patch.dict("os.environ", {"BLUESKY_REPORT_OUTPUT": str(path)}):
                create_report_prs.main()

            path.write_text(json.dumps({"proposals": [{"b64": "one"}]}))
            with (
                mock.patch.dict("os.environ", {"BLUESKY_REPORT_OUTPUT": str(path)}),
                mock.patch.object(
                    create_report_prs, "create_pr_for_proposal", return_value="branch"
                ),
            ):
                create_report_prs.main()

    def test_create_pr_handles_missing_existing_and_command_failure(self):
        self.assertIsNone(create_report_prs.create_pr_for_proposal({}))
        with mock.patch.object(
            create_report_prs, "has_remote_branch", return_value=True
        ):
            self.assertIsNone(create_report_prs.create_pr_for_proposal({"b64": "one"}))

    def test_create_report_storage_and_staging_helpers(self):
        completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with mock.patch.object(subprocess, "run", return_value=completed):
            self.assertIs(create_report_prs.run_command(["true"]), completed)

        remote = subprocess.CompletedProcess(
            [], 0, stdout="hash refs/head\n", stderr=""
        )
        with mock.patch.object(create_report_prs, "run_command", return_value=remote):
            self.assertTrue(create_report_prs.has_remote_branch("branch"))

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jokebook.json"
            self.assertEqual(create_report_prs.load_jokebook(path), {"jokes": []})
            create_report_prs.save_jokebook({"jokes": ["one"]}, path)
            self.assertEqual(create_report_prs.load_jokebook(path), {"jokes": ["one"]})
            path.write_text("[]", encoding="utf-8")
            self.assertEqual(create_report_prs.load_jokebook(path), {"jokes": []})

        with mock.patch.object(
            create_report_prs, "load_jokebook", return_value={"jokes": []}
        ):
            self.assertFalse(
                create_report_prs._stage_jokebook_change("missing", "hash")
            )

        with mock.patch.object(
            create_report_prs.joke_denylist,
            "load_denylist",
            return_value={"jokes": [{"b64": "one"}]},
        ):
            self.assertFalse(
                create_report_prs._stage_denylist_change(
                    {"source_post_uri": "post"}, "one", "hash"
                )
            )

        with (
            mock.patch.object(
                create_report_prs, "has_remote_branch", return_value=False
            ),
            mock.patch.object(
                create_report_prs, "has_open_pr_for_branch", return_value=False
            ),
            mock.patch.object(
                create_report_prs,
                "run_command",
                side_effect=subprocess.CalledProcessError(1, "git"),
            ),
        ):
            self.assertIsNone(create_report_prs.create_pr_for_proposal({"b64": "one"}))

    def test_process_reports_main_persists_summary_and_output(self):
        proposal = {"source_reply_uri": "at://reply"}
        state = {"reports": {"acknowledged_reply_uris": []}}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "reports.json"
            with (
                mock.patch.dict("os.environ", {"BLUESKY_REPORT_OUTPUT": str(output)}),
                mock.patch.object(
                    process_reports.bot_state, "load_state", return_value=state
                ),
                mock.patch.object(
                    process_reports.joke_denylist,
                    "load_denylist",
                    return_value={"jokes": []},
                ),
                mock.patch.object(
                    process_reports, "login_client", return_value=(mock.Mock(), "bot")
                ),
                mock.patch.object(
                    process_reports, "delete_approved_report_posts", return_value=1
                ),
                mock.patch.object(
                    process_reports,
                    "collect_report_proposals",
                    return_value=([proposal], {"at://notification"}, 2),
                ),
                mock.patch.object(
                    process_reports, "acknowledge_report", return_value=(True, False)
                ),
                mock.patch.object(process_reports.bot_state, "save_state"),
            ):
                process_reports.main()

            self.assertEqual(json.loads(output.read_text())["proposal_count"], 1)


class StarterPackCommandCoverageTests(unittest.TestCase):
    def test_load_config_normalises_valid_payload_and_handles_invalid_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "starter.json"
            with mock.patch.object(manage_starter_pack, "_CONFIG_PATH", path):
                path.write_text("invalid", encoding="utf-8")
                self.assertFalse(
                    manage_starter_pack.load_starter_pack_config()["starter_pack"][
                        "enabled"
                    ]
                )
                path.write_text("[]", encoding="utf-8")
                self.assertFalse(
                    manage_starter_pack.load_starter_pack_config()["starter_pack"][
                        "enabled"
                    ]
                )
                path.write_text('{"starter_pack": []}', encoding="utf-8")
                self.assertFalse(
                    manage_starter_pack.load_starter_pack_config()["starter_pack"][
                        "enabled"
                    ]
                )
                path.write_text(
                    json.dumps(
                        {
                            "starter_pack": {
                                "enabled": True,
                                "name": " Custom ",
                                "description": " Description ",
                                "source_list_uri": " at://list ",
                                "record_key": " key ",
                                "starter_pack_uri": " at://pack ",
                                "sync": {
                                    "follow_list_members": False,
                                    "upsert_record": False,
                                },
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                loaded = manage_starter_pack.load_starter_pack_config()["starter_pack"]
                self.assertEqual(loaded["name"], "Custom")
                self.assertFalse(loaded["sync"]["follow_list_members"])

    def test_pull_handler_updates_config_and_handles_noop_dry_run_and_error(self):
        cfg = {"name": "Old", "description": "Old"}
        cases = (
            ({}, False, 0),
            ({"name": "New"}, True, 0),
            ({"name": "New"}, False, 0),
        )
        for updates, dry_run, expected in cases:
            with (
                self.subTest(updates=updates, dry_run=dry_run),
                mock.patch.object(
                    manage_starter_pack,
                    "login_client",
                    return_value=(mock.Mock(), "bot"),
                ),
                mock.patch.object(
                    manage_starter_pack,
                    "pull_starter_pack_record",
                    return_value=updates,
                ),
                mock.patch.object(
                    manage_starter_pack, "write_starter_pack_config_updates"
                ) as write,
            ):
                self.assertEqual(
                    manage_starter_pack._handle_pull_mode(cfg, dry_run), expected
                )
                self.assertEqual(write.called, bool(updates) and not dry_run)

        with mock.patch.object(
            manage_starter_pack, "login_client", side_effect=ValueError("bad")
        ):
            self.assertEqual(manage_starter_pack._handle_pull_mode(cfg, False), 1)

    def test_setup_handler_runs_enabled_actions_and_handles_error(self):
        cfg = {
            "sync": {"upsert_record": True, "follow_list_members": True},
        }
        args = SimpleNamespace(mode="sync")
        with (
            mock.patch.object(
                manage_starter_pack, "login_client", return_value=(mock.Mock(), "bot")
            ),
            mock.patch.object(
                manage_starter_pack, "fetch_list_member_dids", return_value={"did:one"}
            ),
            mock.patch.object(
                manage_starter_pack,
                "upsert_starter_pack_record",
                return_value="at://pack",
            ),
            mock.patch.object(
                manage_starter_pack,
                "ensure_following_list_members",
                return_value=(1, 2),
            ),
        ):
            self.assertEqual(
                manage_starter_pack._handle_setup_sync_mode(
                    cfg, "at://list", args, False, 0
                ),
                0,
            )

        with mock.patch.object(
            manage_starter_pack, "login_client", side_effect=ValueError("bad")
        ):
            self.assertEqual(
                manage_starter_pack._handle_setup_sync_mode(
                    cfg, "at://list", args, False, 0
                ),
                1,
            )

    def test_main_routes_disabled_pull_invalid_and_setup_modes(self):
        controls = {"dry_run": False, "action_delay_seconds": 0}
        cases = (
            ({"enabled": False}, "setup", 0),
            ({"enabled": True}, "pull", 7),
            ({"enabled": True, "source_list_uri": ""}, "setup", 2),
            ({"enabled": True, "source_list_uri": "https://bad"}, "setup", 2),
            ({"enabled": True, "source_list_uri": "at://list"}, "setup", 8),
        )
        for cfg, mode, expected in cases:
            with (
                self.subTest(mode=mode, cfg=cfg),
                mock.patch.object(
                    manage_starter_pack,
                    "_parse_args",
                    return_value=SimpleNamespace(mode=mode),
                ),
                mock.patch.object(
                    manage_starter_pack, "get_runtime_controls", return_value=controls
                ),
                mock.patch.object(
                    manage_starter_pack,
                    "load_starter_pack_config",
                    return_value={"starter_pack": cfg},
                ),
                mock.patch.object(
                    manage_starter_pack, "_handle_pull_mode", return_value=7
                ),
                mock.patch.object(
                    manage_starter_pack, "_handle_setup_sync_mode", return_value=8
                ),
            ):
                self.assertEqual(manage_starter_pack.main(), expected)


class UnfollowCommandCoverageTests(unittest.TestCase):
    def test_load_source_list_uri_handles_invalid_and_enabled_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "starter.json"
            self.assertEqual(unfollow._load_source_list_uri(path), "")
            for payload in ("invalid", "[]", '{"starter_pack": []}'):
                path.write_text(payload, encoding="utf-8")
                self.assertEqual(unfollow._load_source_list_uri(path), "")
            path.write_text(
                '{"starter_pack": {"enabled": false, "source_list_uri": "at://list"}}',
                encoding="utf-8",
            )
            self.assertEqual(unfollow._load_source_list_uri(path), "")
            path.write_text(
                '{"starter_pack": {"enabled": true, "source_list_uri": "at://list"}}',
                encoding="utf-8",
            )
            self.assertEqual(unfollow._load_source_list_uri(path), "at://list")

    def test_resolve_ignorable_dids_handles_models_dicts_missing_and_errors(self):
        client = mock.Mock()
        client.get_profile.side_effect = [
            SimpleNamespace(did="did:model"),
            {"did": "did:dict"},
            {},
            ValueError("bad"),
        ]
        with mock.patch.object(
            unfollow, "retry_network_call", side_effect=lambda fn, description: fn()
        ):
            result = unfollow._resolve_ignorable_dids(
                client, ["model", "dict", "missing", "bad"]
            )
        self.assertEqual(result, {"did:model", "did:dict"})

    def test_unfollow_one_and_loop_cover_success_failure_missing_and_throttle(self):
        client = mock.Mock()
        state = {"unfollow_history": {"entries": []}}
        self.assertEqual(
            unfollow._unfollow_one(client, state, "did", "uri", True), (True, False)
        )
        with mock.patch.object(
            unfollow, "retry_network_call", side_effect=lambda fn, description: fn()
        ):
            self.assertEqual(
                unfollow._unfollow_one(client, state, "did", "uri", False),
                (True, False),
            )
        with mock.patch.object(
            unfollow,
            "retry_network_call",
            side_effect=requests.RequestException("429 rate limit"),
        ):
            self.assertEqual(
                unfollow._unfollow_one(client, state, "did", "uri", False),
                (False, True),
            )

        with (
            mock.patch.object(
                unfollow, "_unfollow_one", side_effect=[(True, False), (False, True)]
            ),
            mock.patch.object(unfollow, "_pause_after_unfollow"),
        ):
            result = unfollow._execute_unfollow_loop(
                client,
                state,
                ["missing", "ok", "throttle"],
                {"ok": "uri", "throttle": "uri"},
                False,
                0,
                1,
                0,
            )
        self.assertEqual(result, (1, 1, 1, True))

    def test_pause_after_unfollow_applies_action_and_batch_delays(self):
        with mock.patch.object(unfollow.time, "sleep") as sleep:
            unfollow._pause_after_unfollow(2, 3, 1.0, 2, 5.0)
        self.assertEqual(sleep.call_args_list, [mock.call(1.0), mock.call(5.0)])


class SocialCommandMainCoverageTests(unittest.TestCase):
    def test_main_runs_joke_reply_flow_and_persists_social_state(self):
        client = mock.Mock()
        state = {"social": "state"}
        with (
            mock.patch.object(
                follows_and_likes,
                "get_runtime_controls",
                return_value={"dry_run": False, "action_delay_seconds": 0},
            ),
            mock.patch.object(
                follows_and_likes, "login_client", return_value=(client, "bot.test")
            ),
            mock.patch.object(
                follows_and_likes.blocks, "reconcile_configured_blocks", return_value=0
            ),
            mock.patch.object(
                follows_and_likes.bot_state, "load_state", return_value=state
            ),
            mock.patch.object(follows_and_likes, "follow_back"),
            mock.patch.object(follows_and_likes, "follow_interactors", return_value=1),
            mock.patch.object(
                follows_and_likes, "track_starter_pack_follows", return_value=1
            ),
            mock.patch.object(
                follows_and_likes, "reply_to_joke_requests", return_value=1
            ) as reply,
            mock.patch.object(follows_and_likes, "like_replies", return_value=1),
            mock.patch.object(follows_and_likes.bot_state, "save_state") as save,
        ):
            follows_and_likes.main()

        reply.assert_called_once()
        save.assert_called_once_with(state, domains="social")

    def test_main_counts_joke_reply_failure_as_failed_social_action(self):
        client = mock.Mock()
        state = {}
        with (
            mock.patch.object(
                follows_and_likes,
                "get_runtime_controls",
                return_value={"dry_run": True, "action_delay_seconds": 1},
            ),
            mock.patch.object(
                follows_and_likes, "login_client", return_value=(client, "bot.test")
            ),
            mock.patch.object(
                follows_and_likes.blocks, "reconcile_configured_blocks", return_value=1
            ),
            mock.patch.object(
                follows_and_likes.bot_state, "load_state", return_value=state
            ),
            mock.patch.object(follows_and_likes, "follow_back"),
            mock.patch.object(follows_and_likes, "follow_interactors", return_value=0),
            mock.patch.object(
                follows_and_likes, "track_starter_pack_follows", return_value=0
            ),
            mock.patch.object(
                follows_and_likes,
                "reply_to_joke_requests",
                side_effect=requests.RequestException("offline"),
            ),
            mock.patch.object(follows_and_likes, "like_replies", return_value=0),
            mock.patch.object(follows_and_likes.bot_state, "save_state"),
            self.assertRaises(RuntimeError),
        ):
            follows_and_likes.main()
