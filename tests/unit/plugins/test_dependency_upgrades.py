# -*- coding: utf-8 -*-
"""Run actual upgrade boundaries outside the repository-wide SDK mocks."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_shared_dependency_upgrades(tmp_path):
    fixtures = Path(__file__).resolve().parents[2] / "fixtures"
    suites = (
        fixtures / "shared_dependencies/upgrade_suite.py",
        fixtures / "channel_plugins/dependency_upgrade_runtime_suite.py",
    )
    for suite in suites:
        _run_suite(suite, tmp_path / suite.stem)


def _run_suite(suite, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; sys.path.insert(0, sys.argv.pop(1)); "
            "import pytest; raise SystemExit(pytest.main(sys.argv[1:]))",
            str(Path(pytest.__file__).resolve().parents[1]),
            "--confcutdir",
            str(suite.parent),
            str(suite),
            "-q",
        ],
        env={
            **os.environ,
            "QWENPAW_WORKING_DIR": str(tmp_path / "working"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secret"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backup"),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
