"""Deterministic tests for provider health monitoring."""

import os
import unittest
from unittest import mock

import bluesky_joke_providers
import bluesky_state
from scripts import update_provider_health


class ProviderHealthTests(unittest.TestCase):
    def test_all_providers_report_success_for_valid_response(self):
        for provider_name in update_provider_health.ALL_PROVIDERS:
            with self.subTest(provider=provider_name):
                fetch_provider = mock.Mock(return_value="A deterministic joke")
                with mock.patch.dict(
                    os.environ, {"API_NINJAS_API_KEY": "test-key"}, clear=False
                ):
                    with mock.patch.dict(
                        bluesky_joke_providers.PROVIDERS,
                        {provider_name: fetch_provider},
                        clear=False,
                    ):
                        result = update_provider_health.check_provider_health(
                            provider_name
                        )

                self.assertTrue(result["success"])
                self.assertTrue(result["configured"])
                self.assertIsNone(result["error"])
                fetch_provider.assert_called_once_with()

    def test_provider_exception_is_recorded_as_failure(self):
        with mock.patch.dict(
            bluesky_joke_providers.PROVIDERS,
            {"jokeapi": mock.Mock(side_effect=TimeoutError("timed out"))},
            clear=False,
        ):
            result = update_provider_health.check_provider_health("jokeapi")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "TimeoutError: timed out")

    def test_api_ninjas_without_key_is_not_configured(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            result = update_provider_health.check_provider_health("api_ninjas")

        self.assertIsNone(result["success"])
        self.assertFalse(result["configured"])
        self.assertEqual(result["error"], "API_NINJAS_API_KEY is not set")

    def test_health_state_tracks_failures_and_recovery(self):
        state = bluesky_state._default_state()
        failed = {
            "jokeapi": {
                "success": False,
                "configured": True,
                "error": "TimeoutError: timed out",
                "check_at": 100,
            }
        }

        health_checks = update_provider_health._apply_health_results(state, failed)
        self.assertEqual(health_checks["jokeapi"]["consecutive_failures"], 1)

        health_checks = update_provider_health._apply_health_results(state, failed)
        self.assertEqual(
            update_provider_health._critical_failures(health_checks), [("jokeapi", 2)]
        )

        recovered = update_provider_health._apply_health_results(
            state,
            {
                "jokeapi": {
                    "success": True,
                    "configured": True,
                    "error": None,
                    "check_at": 200,
                }
            },
        )

        self.assertTrue(recovered["jokeapi"]["last_check_success"])
        self.assertEqual(recovered["jokeapi"]["consecutive_failures"], 0)
        self.assertEqual(update_provider_health._critical_failures(recovered), [])

    def test_unconfigured_provider_resets_failure_streak(self):
        state = bluesky_state._default_state()
        state["provider"]["health_checks"]["api_ninjas"] = {
            "last_check_success": False,
            "consecutive_failures": 3,
        }

        health_checks = update_provider_health._apply_health_results(
            state,
            {
                "api_ninjas": {
                    "success": None,
                    "configured": False,
                    "error": "API_NINJAS_API_KEY is not set",
                    "check_at": 300,
                }
            },
        )

        self.assertIsNone(health_checks["api_ninjas"]["last_check_success"])
        self.assertEqual(health_checks["api_ninjas"]["consecutive_failures"], 0)


if __name__ == "__main__":
    unittest.main()
