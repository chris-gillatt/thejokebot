import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import bluesky_collect_dashboard_metrics
import bluesky_common
import bluesky_config
import bluesky_create_report_prs
import bluesky_denylist
import bluesky_joke_providers
import bluesky_manage_starter_pack
import bluesky_process_reports
import bluesky_state
import bluesky_unfollow
from thejokebot import paths


class RepositoryPathTests(unittest.TestCase):
    def test_defaults_resolve_to_repository_owned_paths(self):
        repository_root = Path(__file__).resolve().parents[1]

        self.assertEqual(paths.PROJECT_ROOT, repository_root)
        self.assertEqual(paths.ENV_FILE, repository_root / ".env")
        self.assertEqual(paths.RESOURCES_DIR, repository_root / "resources")
        self.assertEqual(paths.STATE_DIR, repository_root / "state")
        self.assertEqual(paths.DASHBOARD_DIR, repository_root / "dashboard")
        self.assertEqual(paths.AGENT_TMP_DIR, repository_root / ".agent-tmp")
        self.assertEqual(
            bluesky_common.DEFAULT_SESSION_FILE_PATH,
            str(repository_root / ".agent-tmp" / "bluesky_session.txt"),
        )
        self.assertEqual(
            bluesky_config._CONFIG_PATH,
            repository_root / "resources" / "jokebot_runtime_config.json",
        )
        self.assertEqual(
            bluesky_state.STATE_FILE, str(repository_root / "bot_state.json")
        )
        self.assertEqual(
            bluesky_denylist.DENYLIST_FILE,
            repository_root / "resources" / "jokebot_denylist.json",
        )
        self.assertEqual(
            bluesky_joke_providers._JOKEBOOK_PATH,
            repository_root / "resources" / "jokebot_jokebook.json",
        )
        self.assertEqual(
            bluesky_manage_starter_pack._CONFIG_PATH,
            repository_root / "resources" / "jokebot_starter_pack.json",
        )
        self.assertEqual(
            bluesky_unfollow._STARTER_PACK_CONFIG_PATH,
            repository_root / "resources" / "jokebot_starter_pack.json",
        )
        self.assertEqual(
            bluesky_collect_dashboard_metrics.METRICS_FILE,
            repository_root / "dashboard" / "data" / "metrics.json",
        )
        self.assertEqual(
            bluesky_create_report_prs.DEFAULT_PROPOSALS_PATH,
            repository_root / ".agent-tmp" / "report_proposals.json",
        )
        self.assertEqual(
            bluesky_process_reports.DEFAULT_OUTPUT_PATH,
            repository_root / ".agent-tmp" / "report_proposals.json",
        )

    def test_package_root_is_independent_of_working_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from thejokebot.paths import PROJECT_ROOT; print(PROJECT_ROOT)",
                ],
                cwd=temporary_directory,
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertEqual(
            result.stdout.strip(), str(Path(__file__).resolve().parents[1])
        )


if __name__ == "__main__":
    unittest.main()
