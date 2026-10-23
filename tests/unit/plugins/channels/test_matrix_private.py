# -*- coding: utf-8 -*-
"""Isolated private Matrix business entry; artifact has its own thin entry."""
import os
from pathlib import Path
import subprocess
import sys


def test_matrix_private_business(tmp_path):
    suites = Path(__file__).resolve().parents[3] / "fixtures/channel_plugins"
    names = (
        "matrix_native_auth_suite.py",
        "matrix_native_lifecycle_suite.py",
        "matrix_native_media_suite.py",
        "matrix_native_ingress_suite.py",
        "matrix_crypto_boundary_suite.py",
        "matrix_driver_response_suite.py",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "pytest",
            "-p",
            "pytest_asyncio.plugin",
            "--confcutdir",
            str(suites),
            *[str(suites / name) for name in names],
            "-q",
        ],
        env={
            **os.environ,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "QWENPAW_RUNTIME_ID": "matrix-private-test",
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
