# -*- coding: utf-8 -*-
"""Execute G1 official discovery contracts without global SDK mocks."""

import os
from pathlib import Path
import subprocess
import sys


def test_official_g1_contracts(tmp_path):
    """Exercise real host imports using temporary work and secret roots."""
    suite = (
        Path(__file__).resolve().parents[3]
        / "fixtures/channel_plugins/official_g1_suite.py"
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
            str(suite.with_name("official_g1_fix_suite.py")),
            "-q",
        ],
        env={
            **os.environ,
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backups"),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
