# -*- coding: utf-8 -*-
"""Run each actual G2 Agent responsibility in a separate isolated process."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "case",
    [
        "test_mqtt_formal_zip_real_agent_session_and_worker_exit",
        "test_mattermost_formal_zip_real_agent_session_and_worker_exit",
    ],
)
def test_g2_actual_agent(tmp_path, case):
    suite = (
        Path(__file__).resolve().parents[3]
        / "fixtures/channel_plugins/g2_actual_agent_suite.py"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "pytest",
            "--confcutdir",
            str(suite.parent),
            str(suite) + "::" + case,
            "-q",
            "-s",
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
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout)
