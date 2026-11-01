from importlib.metadata import metadata, version

import thejokebot


def test_runtime_version_uses_installed_project_metadata():
    assert thejokebot.__version__ == version("thejokebot")
    assert thejokebot.__version__ == "1.0.0"


def test_installed_package_declares_python_314_minimum():
    assert metadata("thejokebot")["Requires-Python"] == ">=3.14"
