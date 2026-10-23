# -*- coding: utf-8 -*-
"""Run lease/OS-lock contracts outside repository-wide SDK replacements."""

from pathlib import Path
import subprocess
import sys


def test_dependency_lease_cleanup():
    suite = (
        Path(__file__).resolve().parents[2]
        / "fixtures/dependency_leases/cleanup_suite.py"
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
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
