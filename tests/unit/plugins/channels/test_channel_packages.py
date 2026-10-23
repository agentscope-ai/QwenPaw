# -*- coding: utf-8 -*-
"""Run plugin contracts without tests/conftest.py's global SDK mocks."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

SUITE = (
    Path(__file__).resolve().parents[3]
    / "fixtures/channel_plugins/registration_suite.py"
)


@pytest.mark.parametrize(
    "suite_name",
    [
        "registration_suite.py",
        "dingtalk_registration_suite.py",
        "contract_suite.py",
        "packaging_suite.py",
    ],
)
def test_channel_packages(tmp_path, suite_name):
    """The subprocess uses real host modules and a temporary working dir."""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "pytest",
            "--confcutdir",
            str(SUITE.parent),
            str(SUITE.with_name(suite_name)),
            "-q",
        ],
        env={**os.environ, "QWENPAW_WORKING_DIR": str(tmp_path / "qwenpaw")},
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
