# -*- coding: utf-8 -*-
# pylint: disable=missing-function-docstring,duplicate-code
"""Run protocol close ownership checks in an isolated interpreter."""

import os
from pathlib import Path
import subprocess
import sys


def test_protocol_close_waiter_ownership(tmp_path):
    suite = (
        Path(__file__).resolve().parents[2]
        / "fixtures/channel_plugins/transport_close_suite.py"
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
        ],
        env={**os.environ, "QWENPAW_WORKING_DIR": str(tmp_path / "host")},
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
