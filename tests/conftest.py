"""Do not publish synthetic test traffic as workflow API usage."""

import os

os.environ["THEJOKEBOT_API_USAGE_ENABLED"] = "false"
