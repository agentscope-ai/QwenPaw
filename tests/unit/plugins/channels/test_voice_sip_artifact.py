# -*- coding: utf-8 -*-
"""Thin isolated entry; artifact preparation does not run old call suites."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("key", ["voice", "sip"])
def test_voice_sip_artifact_contracts(tmp_path, key):
    fixtures = Path(__file__).resolve().parents[3] / "fixtures/channel_plugins"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "pytest",
            "-p",
            "pytest_asyncio.plugin",
            "--confcutdir",
            str(fixtures),
            str(fixtures / (key + "_artifact_suite.py")),
            "-q",
        ],
        env={
            **os.environ,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "QWENPAW_RUNTIME_ID": key + "-artifact-test",
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
