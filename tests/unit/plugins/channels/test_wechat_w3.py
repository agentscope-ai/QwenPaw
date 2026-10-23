# -*- coding: utf-8 -*-
"""Bounded normal entrypoints for independent W3 backend responsibilities."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "suite,selection",
    [
        ("qrcode_state_suite.py", ""),
        (
            "wechat_w3_router_suite.py",
            "actual_http or cancel_and_disconnect or actual_outer_http",
        ),
        (
            "wechat_w3_router_suite.py",
            "provenance or persistence_failure or manual_edit",
        ),
        ("wechat_w3_lifecycle_suite.py", ""),
        ("wechat_w3_runtime_cli_suite.py", ""),
        ("wechat_w3_manual_scope_suite.py", ""),
        ("wechat_w3_protected_save_suite.py", ""),
        ("wechat_w3_startup_fencing_suite.py", ""),
    ],
)
def test_wechat_w3_backend_responsibility_group(tmp_path, suite, selection):
    path = (
        Path(__file__).resolve().parents[3]
        / "fixtures/channel_plugins"
        / suite
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "pytest",
            "-p",
            "pytest_asyncio.plugin",
            "--confcutdir",
            str(path.parent),
            str(path),
            "-k",
            selection,
            "-q",
        ],
        env={
            **os.environ,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secret"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backup"),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
