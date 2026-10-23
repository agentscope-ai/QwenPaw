# -*- coding: utf-8 -*-
"""Keep Docker upgrade acceptance outside global SDK MagicMocks."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(
    os.name == "nt",
    reason="Docker entrypoint acceptance requires /bin/sh",
)
def test_docker_channel_upgrade_contracts(tmp_path):
    fixtures = Path(__file__).resolve().parents[2] / "fixtures/channel_plugins"
    spec = importlib.util.spec_from_file_location(
        "docker_upgrade_support",
        fixtures / "wheel_upgrade_support.py",
    )
    assert spec is not None and spec.loader is not None
    support = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(support)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "pytest",
            "--confcutdir",
            str(fixtures),
            str(fixtures / "docker_upgrade_suite.py"),
            "-q",
        ],
        env=support.clean_environment(tmp_path),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=360,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
