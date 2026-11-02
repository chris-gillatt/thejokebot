"""Verify native deferred annotation introspection on the supported Python floor."""

import annotationlib
import ast
import importlib
import inspect
import typing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _annotated_modules():
    for directory in ("src", "scripts"):
        for path in sorted((ROOT / directory).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if not any(
                isinstance(node, ast.FunctionDef)
                and (node.returns or any(arg.annotation for arg in node.args.args))
                for node in tree.body
            ):
                continue
            relative = path.relative_to(ROOT / "src" if directory == "src" else ROOT)
            yield ".".join(relative.with_suffix("").parts), path


@pytest.mark.parametrize("name,path", list(_annotated_modules()))
def test_native_annotations_resolve_without_stringification(name, path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert not any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    ), f"{path.relative_to(ROOT)} still opts into stringified annotations"
    module = importlib.import_module(name)
    functions = [
        value
        for value in vars(module).values()
        if inspect.isfunction(value) and value.__module__ == name
    ]
    for function in functions:
        annotations = annotationlib.get_annotations(function)
        normalised = {
            key: type(None) if value is None else value
            for key, value in annotations.items()
        }
        assert normalised == typing.get_type_hints(function)


def test_native_forward_reference_is_deferred_until_introspection():
    namespace = {}
    exec(
        compile(
            "def identity(value: Later) -> Later:\n"
            "    return value\n"
            "class Later:\n"
            "    pass\n",
            "<native-annotations>",
            "exec",
            dont_inherit=True,
        ),
        namespace,
    )
    identity = namespace["identity"]
    later = namespace["Later"]
    assert identity(later) is later
    assert identity.__annotations__ == {"value": later, "return": later}
    assert annotationlib.get_annotations(
        identity, format=annotationlib.Format.STRING
    ) == {
        "value": "Later",
        "return": "Later",
    }
