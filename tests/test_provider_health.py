"""
Health checks for joke providers.

Verifies that primary and backup providers are responding correctly.
These tests are run on a schedule by provider_health_check.yml workflow
to alert maintainers of provider outages or consistent failures.
"""

import os
import unittest
from unittest import mock

import bluesky_joke_providers
from scripts import update_provider_health


class ProviderHealthTests(unittest.TestCase):
    """Test each provider for basic connectivity and error handling."""

    def test_icanhazdadjoke_health(self):
        """icanhazdadjoke should return a non-empty string."""
        joke = bluesky_joke_providers.fetch_from_icanhazdadjoke()
        self.assertIsInstance(joke, str)
        self.assertGreater(len(joke), 0)

    def test_jokeapi_health(self):
        """jokeapi should return a non-empty string."""
        joke = bluesky_joke_providers.fetch_from_jokeapi()
        self.assertIsInstance(joke, str)
        self.assertGreater(len(joke), 0)

    def test_groandeck_health(self):
        """groandeck should return a non-empty string."""
        joke = bluesky_joke_providers.fetch_from_groandeck()
        self.assertIsInstance(joke, str)
        self.assertGreater(len(joke), 0)

    def test_syrsly_health(self):
        """syrsly (backup provider) should return a non-empty string."""
        joke = bluesky_joke_providers.fetch_from_syrsly()
        self.assertIsInstance(joke, str)
        self.assertGreater(len(joke), 0)

    def test_api_ninjas_health(self):
        """api_ninjas (backup provider) should return a non-empty string or raise ValueError."""
        try:
            joke = bluesky_joke_providers.fetch_from_api_ninjas()
            self.assertIsInstance(joke, str)
            self.assertGreater(len(joke), 0)
        except ValueError as e:
            # Expected if API_NINJAS_API_KEY is not set
            self.assertIn("API_NINJAS_API_KEY", str(e))

    def test_jokebot_jokebook_health(self):
        """jokebot_jokebook (fallback) should always return a non-empty string."""
        joke = bluesky_joke_providers.fetch_from_jokebot_jokebook()
        self.assertIsInstance(joke, str)
        self.assertGreater(len(joke), 0)

    def test_api_ninjas_without_key_is_not_configured(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            result = update_provider_health.check_provider_health("api_ninjas")

        self.assertIsNone(result["success"])
        self.assertFalse(result["configured"])
        self.assertEqual(result["error"], "API_NINJAS_API_KEY is not set")


if __name__ == "__main__":
    unittest.main()
