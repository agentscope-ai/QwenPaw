# -*- coding: utf-8 -*-
"""Keep Windows home regressions free of repository-wide SDK replacements."""

from pathlib import Path
import subprocess
import sys


def test_windows_worker_home():
    suite = (
        Path(__file__).resolve().parents[2]
        / "fixtures/plugin_execution/windows_home_suite.py"
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
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
