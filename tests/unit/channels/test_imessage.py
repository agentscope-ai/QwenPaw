# -*- coding: utf-8 -*-
"""Isolated official iMessage tests after moving platform code out of Core.

Original 37 direct / 19 inherited oracles are retained in the scoped suites.
No legacy Channel compatibility class or global SDK mocks are used.
"""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "suite",
    [
        "imessage_native_suite.py",
        "imessage_private_process_suite.py",
        "imessage_trusted_context_suite.py",
        "imessage_closeout_suite.py",
        "imessage_lifecycle_suite.py",
        "imessage_remaining_oracle_suite.py",
        "imessage_media_race_suite.py",
    ],
)
def test_imessage_private_and_formal_contracts(suite, tmp_path):
    fixture = Path(__file__).resolve().parents[2] / "fixtures/channel_plugins"
    for name in ("home", "work", "secret", "backup", "tmp"):
        (tmp_path / name).mkdir()
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "pytest",
            "-p",
            "pytest_asyncio.plugin",
            "--confcutdir",
            str(fixture),
            str(fixture / suite),
            "-q",
            "--tb=short",
        ],
        env={
            **os.environ,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "HOME": str(tmp_path / "home"),
            "TMPDIR": str(tmp_path / "tmp"),
            "TMP": str(tmp_path / "tmp"),
            "TEMP": str(tmp_path / "tmp"),
            "QWENPAW_WORKING_DIR": str(tmp_path / "work"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secret"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backup"),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
