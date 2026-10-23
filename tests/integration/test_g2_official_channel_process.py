# -*- coding: utf-8 -*-
"""Run official MQTT/Mattermost workers outside global SDK monkeypatches."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "suite_name",
    [
        "g2_official_process_suite.py",
        "g2_lifecycle_suite.py",
        "g2_services_suite.py",
        "g2_business_suite.py",
        "g2_legacy_process_suite.py",
    ],
)
def test_g2_official_channel_process(tmp_path, suite_name):
    suite = (
        Path(__file__).resolve().parents[1]
        / "fixtures/channel_plugins"
        / suite_name
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
        env={
            **os.environ,
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
