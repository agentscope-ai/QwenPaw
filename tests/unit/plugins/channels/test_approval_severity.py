# -*- coding: utf-8 -*-
"""Run only approval severity regressions with real SDKs in clean children."""

import os
from pathlib import Path
import subprocess
import sys


def test_approval_severity_isolated(tmp_path):
    suite = (
        Path(__file__).resolve().parents[3]
        / "fixtures/channel_plugins/approval_severity_suite.py"
    )
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    for key, name in (
        ("HOME", "home"),
        ("TMPDIR", "tmp"),
        ("QWENPAW_WORKING_DIR", "working"),
        ("QWENPAW_SECRET_DIR", "secret"),
        ("QWENPAW_BACKUP_DIR", "backup"),
    ):
        directory = tmp_path / name
        directory.mkdir()
        env[key] = str(directory)
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
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
