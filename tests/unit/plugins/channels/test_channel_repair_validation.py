# -*- coding: utf-8 -*-
"""Run repair validation contracts without repository-wide SDK mocks."""

import os
from pathlib import Path
import subprocess
import sys


def test_channel_repair_validation_contracts(tmp_path):
    """
    Run the real Loader and API regression suite with SDK imports guarded.
    """
    suite = Path(__file__).resolve().parents[3] / (
        "fixtures/channel_plugins/repair_validation_suite.py"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--confcutdir",
            str(suite.parent),
            str(suite),
            "-q",
        ],
        env={
            **os.environ,
            "PYTHONPATH": str(suite.parents[3] / "src"),
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
