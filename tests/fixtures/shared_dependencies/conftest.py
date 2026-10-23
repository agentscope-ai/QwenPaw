# -*- coding: utf-8 -*-
"""Independent evidence without global SDK mocks or host model imports."""

import importlib.abc
import os
from pathlib import Path
import sys

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src"
sys.path.insert(0, str(SOURCE_ROOT))
BLOCKED = (
    "qwenpaw.agents",
    "agentscope",
    "agentscope_runtime",
    "lark_oapi",
    "dingtalk_stream",
    "alibabacloud_dingtalk",
    "qwenpaw.app.channels.feishu",
    "qwenpaw.app.channels.dingtalk",
)
ATTEMPTS = []


def blocked(name):
    return any(name == part or name.startswith(part + ".") for part in BLOCKED)


class ImportGuard(importlib.abc.MetaPathFinder):
    # Match importlib's callback signature; both optional inputs are unused.
    # pylint: disable-next=unused-argument
    def find_spec(self, fullname, path=None, target=None):
        if blocked(fullname):
            ATTEMPTS.append(fullname)
            raise AssertionError(f"Shared dependencies imported {fullname}")


assert all(
    os.environ.get(name)
    for name in (
        "QWENPAW_WORKING_DIR",
        "QWENPAW_SECRET_DIR",
        "QWENPAW_BACKUP_DIR",
    )
)
assert not any(blocked(name) for name in sys.modules)
sys.meta_path.insert(0, ImportGuard())
importlib.import_module("qwenpaw")

# The existing package compatibility shim probes AgentScope once at import.
# Block that probe, then require zero new attempts from the execution APIs.
assert ATTEMPTS in ([], ["agentscope"]), ATTEMPTS
BASELINE_ATTEMPTS = tuple(ATTEMPTS)
assert not any(blocked(name) for name in sys.modules)


@pytest.fixture(autouse=True)
def verify_import_boundary():
    yield
    assert tuple(ATTEMPTS) == BASELINE_ATTEMPTS, ATTEMPTS
    assert not any(blocked(name) for name in sys.modules)
