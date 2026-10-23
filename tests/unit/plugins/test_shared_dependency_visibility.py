# -*- coding: utf-8 -*-
"""Run real shared-dependency evidence outside repository-wide SDK mocks."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_shared_dependency_visibility(tmp_path):
    suite = Path(__file__).resolve().parents[2] / (
        "fixtures/shared_dependencies/visibility_suite.py"
    )
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
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
