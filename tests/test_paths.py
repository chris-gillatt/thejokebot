import ast
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import bluesky_collect_dashboard_metrics
from thejokebot import runtime as runtime
from thejokebot import config as runtime_config
import bluesky_create_report_prs
from thejokebot import denylist as joke_denylist
from thejokebot import providers as joke_providers
import bluesky_manage_starter_pack
import bluesky_process_reports
from thejokebot import state as bot_state
import bluesky_unfollow
from thejokebot import paths


class RepositoryPathTests(unittest.TestCase):
    def test_first_party_code_does_not_import_deleted_root_modules(self):
        repository_root = Path(__file__).resolve().parents[1]
        deleted_modules = {
            "bluesky_blocks",
            "bluesky_common",
            "bluesky_config",
            "bluesky_denylist",
            "bluesky_follower_utils",
            "bluesky_joke_providers",
            "bluesky_state",
        }
        python_files = list(repository_root.glob("*.py"))
        for directory in ("src", "scripts", "tests"):
            python_files.extend((repository_root / directory).rglob("*.py"))

        stale_imports = []
        for python_file in python_files:
            tree = ast.parse(python_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_modules = {
                        alias.name.split(".", 1)[0] for alias in node.names
                    }
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_modules = {node.module.split(".", 1)[0]}
                else:
                    continue
                for module in deleted_modules & imported_modules:
                    stale_imports.append(
                        f"{python_file.relative_to(repository_root)}:{node.lineno}: {module}"
                    )

        self.assertEqual(stale_imports, [])

    def test_defaults_resolve_to_repository_owned_paths(self):
        repository_root = Path(__file__).resolve().parents[1]

        self.assertEqual(paths.PROJECT_ROOT, repository_root)
        self.assertEqual(paths.ENV_FILE, repository_root / ".env")
        self.assertEqual(paths.RESOURCES_DIR, repository_root / "resources")
        self.assertEqual(paths.STATE_DIR, repository_root / "state")
        self.assertEqual(paths.DASHBOARD_DIR, repository_root / "dashboard")
        self.assertEqual(paths.AGENT_TMP_DIR, repository_root / ".agent-tmp")
        self.assertEqual(
            runtime.DEFAULT_SESSION_FILE_PATH,
            str(repository_root / ".agent-tmp" / "bluesky_session.txt"),
        )
        self.assertEqual(
            runtime_config._CONFIG_PATH,
            repository_root / "resources" / "jokebot_runtime_config.json",
        )
        self.assertEqual(bot_state.STATE_FILE, str(repository_root / "bot_state.json"))
        self.assertEqual(
            joke_denylist.DENYLIST_FILE,
            repository_root / "resources" / "jokebot_denylist.json",
        )
        self.assertEqual(
            joke_providers._JOKEBOOK_PATH,
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
