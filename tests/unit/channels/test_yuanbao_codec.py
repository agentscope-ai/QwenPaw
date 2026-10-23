# -*- coding: utf-8 -*-
"""Isolated entries for current private Yuanbao business oracles."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("suite_name", ["yuanbao_legacy_codec_suite.py"])
def test_yuanbao_current_private_oracles(tmp_path, suite_name):
    suite = (
        Path(__file__).resolve().parents[2]
        / "fixtures/channel_plugins"
        / suite_name
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
