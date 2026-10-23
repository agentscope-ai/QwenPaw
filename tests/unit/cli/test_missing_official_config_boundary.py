# -*- coding: utf-8 -*-
"""Isolated entry for three passive missing-code configuration controls."""

import os
from pathlib import Path
import subprocess
import sys


def test_missing_official_configuration_boundaries(tmp_path):
    suite = (
        Path(__file__).resolve().parents[2]
        / "fixtures/channel_plugins/cli_missing_official_suite.py"
    )
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
            str(suite.parent),
            str(suite),
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
