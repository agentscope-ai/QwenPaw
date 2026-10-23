# -*- coding: utf-8 -*-
"""Run upgrade contracts outside the host suite's global SDK replacements."""

import os
from pathlib import Path
import subprocess
import sys


def test_legacy_channel_upgrade_contracts(tmp_path):
    suite = (
        Path(__file__).resolve().parents[3]
        / "fixtures/channel_plugins/legacy_channel_upgrade_suite.py"
    )
    # Start from a small allowlist: no ambient channel/provider credentials.
    env = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "TMPDIR")
        if key in os.environ
    }
    env.update(
        HOME=str(tmp_path / "home"),
        USERPROFILE=str(tmp_path / "home"),
        QWENPAW_WORKING_DIR=str(tmp_path / "host"),
        QWENPAW_SECRET_DIR=str(tmp_path / "secrets"),
        QWENPAW_BACKUP_DIR=str(tmp_path / "backups"),
        QWENPAW_TELEMETRY_DISABLED="1",
        QWENPAW_RUNNING_IN_CONTAINER="true",
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
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
