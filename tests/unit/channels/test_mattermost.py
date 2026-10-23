# -*- coding: utf-8 -*-
"""Original mattermost tests now exercise Reader/Platform and the host proxy.

Original runtime behavior is verified by g2_official_process_suite,
g2_business_suite, g2_lifecycle_suite and g2_legacy_process_suite.
"""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "suite_name",
    [
        "g2_legacy_environment_suite.py",
        "g2_legacy_mattermost_unit_suite.py",
        "g2_legacy_configuration_suite.py",
    ],
)
def test_mattermost_migrated_unit_contracts(tmp_path, suite_name):
    suite = (
        Path(__file__).resolve().parents[2]
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
            "-k",
            "mattermost or compatibility_reader",
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
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
