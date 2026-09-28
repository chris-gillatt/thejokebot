from importlib.metadata import version

import thejokebot


def test_runtime_version_uses_installed_project_metadata():
    assert thejokebot.__version__ == version("thejokebot")
    assert thejokebot.__version__ == "1.0.0"
