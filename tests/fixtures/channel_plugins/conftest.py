# -*- coding: utf-8 -*-
# pylint: disable=unused-argument
"""Load real plugin modules without the repository's global SDK mocks."""

import importlib.abc
import os
from pathlib import Path
import sys

import pytest

# Package initialization reads global paths and opens its rotating log.
# Give parallel suite hosts separate roots before importing qwenpaw/constants.
if worker := os.environ.get("PYTEST_XDIST_WORKER"):
    working_root = Path(os.environ["QWENPAW_WORKING_DIR"])
    secret_root = Path(
        os.environ.get("QWENPAW_SECRET_DIR", f"{working_root}.secret"),
    )
    backup_root = Path(
        os.environ.get("QWENPAW_BACKUP_DIR", f"{working_root}.backups"),
    )
    os.environ["QWENPAW_WORKING_DIR"] = str(working_root / worker)
    os.environ["QWENPAW_SECRET_DIR"] = str(secret_root / worker)
    os.environ["QWENPAW_BACKUP_DIR"] = str(backup_root / worker)

SOURCE_ROOT = (
    Path(os.environ["QWENPAW_C7_RELEASE_ROOT"])
    if "QWENPAW_C7_RELEASE_ROOT" in os.environ
    else Path(__file__).resolve().parents[3]
) / "src"
SOURCE_ROOT = SOURCE_ROOT.resolve()
sys.path.insert(0, str(SOURCE_ROOT))

BUILTIN_PREFIXES = (
    "qwenpaw.app.channels.feishu",
    "qwenpaw.app.channels.dingtalk",
)


def is_builtin_platform(name):
    """Match implementation modules and their children, not host utilities."""
    return any(
        name == prefix or name.startswith(f"{prefix}.")
        for prefix in BUILTIN_PREFIXES
    )


class NoBuiltinImports(importlib.abc.MetaPathFinder):
    """Block legacy implementations even during runtime suite collection."""

    def find_spec(self, fullname, path=None, target=None):
        if is_builtin_platform(fullname):
            raise AssertionError(f"Unexpected builtin import: {fullname}")


if os.environ.get("QWENPAW_CHANNEL_BLOCK_BUILTINS") == "1":
    assert not any(is_builtin_platform(name) for name in sys.modules)
    sys.meta_path.insert(0, NoBuiltinImports())

qwenpaw = importlib.import_module("qwenpaw")
assert qwenpaw.__file__ is not None
assert Path(qwenpaw.__file__).resolve().is_relative_to(SOURCE_ROOT)


class NoPlatformImports(importlib.abc.MetaPathFinder):
    """Fail even when application code catches a missing SDK import."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "lark_oapi" or fullname.startswith(
            (
                "lark_oapi.",
                "qwenpaw.app.channels.feishu",
                "dingtalk_stream",
                "alibabacloud_",
                "Tea.",
                "qwenpaw.app.channels.dingtalk",
            ),
        ):
            raise AssertionError(f"Unexpected platform import: {fullname}")


@pytest.fixture(autouse=True)
def no_platform_imports(monkeypatch, request):
    """A fresh process prevents cached SDKs from hiding imports."""
    if request.module.__name__.endswith(
        ("feishu_suite", "lifecycle_suite", "dingtalk_suite"),
    ):
        return
    assert "lark_oapi" not in sys.modules
    monkeypatch.setattr(
        sys,
        "meta_path",
        [NoPlatformImports(), *sys.meta_path],
    )
