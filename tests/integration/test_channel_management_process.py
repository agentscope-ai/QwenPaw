# -*- coding: utf-8 -*-
"""Collect G3 real-child proof outside global platform SDK fixtures."""

import os
from pathlib import Path
import subprocess
import sys


def test_channel_management_process(tmp_path):
    for name in (
        "management_process_suite.py",
        "management_ownership_suite.py",
        "management_lifecycle_suite.py",
    ):
        suite = (
            Path(__file__).resolve().parents[1]
            / "fixtures/channel_plugins"
            / name
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
                str(suite.parent),
                str(suite),
                "-q",
            ],
            env={
                **os.environ,
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "QWENPAW_WORKING_DIR": str(tmp_path / (name + "-host")),
                "QWENPAW_SECRET_DIR": str(tmp_path / (name + "-secrets")),
                "QWENPAW_BACKUP_DIR": str(tmp_path / (name + "-backups")),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
