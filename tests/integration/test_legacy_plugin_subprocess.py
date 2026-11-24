# -*- coding: utf-8 -*-
"""Legacy plugins retain their lifecycle behavior across fresh processes."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.integration
@pytest.mark.p0
def test_legacy_plugin_install_upgrade_restart_and_uninstall(tmp_path):
    probe = Path(__file__).parent / "fixtures" / "legacy_plugin_probe.py"
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(
            word in key.upper()
            for word in ("TOKEN", "SECRET", "API_KEY", "APP_KEY", "PASSWORD")
        )
    }
    environment.pop("PYTHONPATH", None)
    environment.pop("QWENPAW_RUNTIME_ID", None)
    environment.update(
        QWENPAW_WORKING_DIR=str(tmp_path / "working"),
        QWENPAW_SECRET_DIR=str(tmp_path / "secrets"),
        XDG_CACHE_HOME=str(tmp_path / "cache"),
        XDG_CONFIG_HOME=str(tmp_path / "config"),
    )
    for phase in ("seed", "cycle", "cold", "uninstall"):
        completed = subprocess.run(
            [sys.executable, str(probe), phase],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        observation = json.loads(completed.stdout.splitlines()[-1])
        assert observation["phase"] == phase and observation["ok"]
