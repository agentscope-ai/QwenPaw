# -*- coding: utf-8 -*-
"""Catalog contracts run without repository-wide SDK mocks."""

import os
from pathlib import Path
import subprocess
import sys


def test_channel_catalog_contracts(tmp_path):
    """Run static catalog and lifecycle identity contracts in isolation."""
    suite = (
        Path(__file__).resolve().parents[3]
        / "fixtures/channel_plugins/catalog_suite.py"
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
            str(suite.with_name("catalog_review_gates_suite.py")),
            str(suite.with_name("sdk_coexistence_suite.py")),
            "-q",
        ],
        env={**os.environ, "QWENPAW_WORKING_DIR": str(tmp_path / "host")},
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
