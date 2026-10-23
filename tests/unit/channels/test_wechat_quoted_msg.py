# -*- coding: utf-8 -*-
"""Original twelve quote oracles plus separately real HTTP/AES IO."""

import os
from pathlib import Path
import subprocess
import sys


def test_wechat_quoted_message_contracts(tmp_path):
    suite = (
        Path(__file__).resolve().parents[2]
        / "fixtures/channel_plugins/wechat_closeout_parser_suite.py"
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
            "PIP_NO_INDEX": "1",
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
