"""Repository-owned paths used by the application checkout."""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parents[1]

ENV_FILE = PROJECT_ROOT / ".env"
RESOURCES_DIR = PROJECT_ROOT / "resources"
STATE_DIR = PROJECT_ROOT / "state"
DASHBOARD_DIR = PROJECT_ROOT / "dashboard"
AGENT_TMP_DIR = PROJECT_ROOT / ".agent-tmp"
LEGACY_STATE_FILE = PROJECT_ROOT / "bot_state.json"
