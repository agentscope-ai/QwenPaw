# -*- coding: utf-8 -*-
"""Run C3 behavioral contracts in hosts without global platform mocks."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("channel", ["feishu", "dingtalk"])
def test_workspace_channel_handoff(channel, tmp_path):
    suite = (
        Path(__file__).resolve().parents[3]
        / "fixtures/channel_plugins/workspace_handoff_suite.py"
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
            *(["-n", "2"] if channel == "feishu" else []),
        ],
        env={
            **os.environ,
            "QWENPAW_C2_CHANNEL": channel,
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
        },
        capture_output=True,
        text=True,
        check=False,
        # C4 admission inspections add bounded child work to every fixture.
        # Feishu serial cases exceed 410s; independent hosts share this cap.
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
