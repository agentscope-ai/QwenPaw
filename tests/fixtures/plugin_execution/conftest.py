# -*- coding: utf-8 -*-
"""Guard real public imports before the isolated test suite is collected."""

import importlib.abc
import os
from pathlib import Path
import sys

import pytest

SOURCE_ROOT = (
    Path(os.environ["QWENPAW_C7_RELEASE_ROOT"])
    if "QWENPAW_C7_RELEASE_ROOT" in os.environ
    else Path(__file__).resolve().parents[3]
) / "src"
SOURCE_ROOT = SOURCE_ROOT.resolve()
sys.path.insert(0, str(SOURCE_ROOT))

BLOCKED = (
    "qwenpaw.app",
    "qwenpaw.channel_protocol",
    "qwenpaw.plugins.loader",
    "qwenpaw.plugins.api",
    "qwenpaw.plugins.registry",
    "lark_oapi",
    "dingtalk_stream",
    "alibabacloud_dingtalk",
)
ATTEMPTS = []


def blocked(name):
    return any(
        name == prefix or name.startswith(prefix + ".") for prefix in BLOCKED
    )


class ImportGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, _path=None, _target=None):
        if blocked(fullname):
            ATTEMPTS.append(fullname)
            raise AssertionError(f"Generic execution imported {fullname}")


assert not any(blocked(name) for name in sys.modules)
sys.meta_path.insert(0, ImportGuard())

qwenpaw = importlib.import_module("qwenpaw")
assert qwenpaw.__file__ is not None
assert Path(qwenpaw.__file__).resolve().is_relative_to(SOURCE_ROOT)


@pytest.fixture(autouse=True)
def verify_import_boundary():
    yield
    assert not ATTEMPTS, f"Caught forbidden imports: {ATTEMPTS}"
