# -*- coding: utf-8 -*-
"""Regression coverage for managed launch and configuration boundaries."""

import json
import os
from pathlib import Path
import subprocess
import sys

from qwenpaw import constant
from qwenpaw.hub import local_provisioner
from tests.unit.hub.factories import runtime_record


def test_managed_startup_ignores_dotenv(tmp_path):
    fake = tmp_path / "repo" / "src" / "qwenpaw" / "constant.py"
    fake.parent.mkdir(parents=True)
    fake.write_text(
        Path(constant.__file__).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "repo" / ".env").write_text(
        "REVIEW_HOST_DOTENV=host\n",
        encoding="utf-8",
    )
    record = runtime_record(tmp_path)
    (record.working_dir / ".env").write_text(
        "PIP_TARGET=/not-allowed\n",
        encoding="utf-8",
    )
    env = local_provisioner.LocalProcessRuntimeProvisioner.runtime_environment(
        record,
        {},
    )
    code = (
        f"import runpy,os,json;runpy.run_path({str(fake)!r});"
        "print(json.dumps([os.getenv('REVIEW_HOST_DOTENV'),"
        "os.getenv('PIP_TARGET')]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == [None, None]


def test_runtime_path_includes_install_scripts(tmp_path, monkeypatch):
    scripts = str(tmp_path / "python" / "Scripts")
    monkeypatch.setattr(
        local_provisioner.sysconfig,
        "get_path",
        lambda _name: scripts,
    )
    env = local_provisioner.LocalProcessRuntimeProvisioner.runtime_environment(
        runtime_record(tmp_path),
        {},
    )
    assert scripts in env["PATH"].split(os.pathsep)
