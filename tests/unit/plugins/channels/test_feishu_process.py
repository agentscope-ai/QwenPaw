# -*- coding: utf-8 -*-
"""Run B3 in an isolated parent without repository-wide SDK replacements."""

import os
from pathlib import Path
import subprocess
import sys


def test_feishu_actual_process(tmp_path):
    suite = (
        Path(__file__).resolve().parents[3]
        / "fixtures/channel_plugins/feishu_process_suite.py"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "pytest",
            "--confcutdir",
            str(suite.parent),
            str(suite),
            "-q",
            "-n",
            "2",
        ],
        env={**os.environ, "QWENPAW_WORKING_DIR": str(tmp_path / "b3-host")},
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
