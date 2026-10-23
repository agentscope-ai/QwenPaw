# -*- coding: utf-8 -*-
"""Shared subprocess mechanics for explicitly mapped isolated test suites."""

import os
from pathlib import Path
import subprocess
import sys

FIXTURE = Path(__file__).resolve().parent / "fixtures/channel_plugins"


def run_isolated_pytest(
    suite,
    *,
    env,
    timeout=None,
    asyncio_plugin=False,
    short_traceback=False,
    confcutdir=None,
    test_filter=None,
):
    targets = [suite] if isinstance(suite, (str, Path)) else list(suite)
    targets = [FIXTURE / target for target in targets]
    command = [sys.executable, "-I", "-m", "pytest"]
    if asyncio_plugin:
        command.extend(["-p", "pytest_asyncio.plugin"])
    cutoff = targets[0].parent if confcutdir is None else confcutdir
    command.extend(["--confcutdir", str(cutoff)])
    command.extend(str(target) for target in targets)
    if test_filter is not None:
        command.extend(["-k", test_filter])
    command.append("-q")
    if short_traceback:
        command.append("--tb=short")
    result = subprocess.run(
        command,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
        **({"timeout": timeout} if timeout is not None else {}),
    )
    assert result.returncode == 0, result.stdout + result.stderr


def run_mapped_suite(suite, tmp_path):
    run_mapped_suites([suite], tmp_path)


def run_mapped_suites(suite, tmp_path):
    names = [suite] if isinstance(suite, str) else list(suite)
    targets = [FIXTURE / name for name in names]
    assert targets and all(target.is_file() for target in targets)
    for name in ("home", "work", "secret", "backup", "tmp"):
        (tmp_path / name).mkdir()
    run_isolated_pytest(
        targets,
        env={
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PIP_NO_INDEX": "1",
            "HOME": str(tmp_path / "home"),
            "TMPDIR": str(tmp_path / "tmp"),
            "TMP": str(tmp_path / "tmp"),
            "TEMP": str(tmp_path / "tmp"),
            "QWENPAW_WORKING_DIR": str(tmp_path / "work"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secret"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backup"),
        },
        timeout=60,
        asyncio_plugin=True,
        short_traceback=True,
        confcutdir=FIXTURE,
    )
