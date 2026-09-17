# -*- coding: utf-8 -*-
"""Exercise real venvs, pip entry points and isolated shell execution."""

import json
import os
import shlex
import subprocess
import sys
import zipfile
import venv
from types import SimpleNamespace

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from qwenpaw.hub import python_environment
from qwenpaw.hub.models import RuntimeRecord, RuntimeState
from qwenpaw.hub.python_environment import (
    apply_python_environment,
    ensure_python_environment,
    environment_root,
)
from qwenpaw.hub.process_isolation import MacOSSeatbeltIsolator


def _record(tmp_path: Path, name: str) -> RuntimeRecord:
    root = tmp_path / name
    for directory in ("working", "logs", "secrets", "backups"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    return RuntimeRecord(
        runtime_id=name,
        tenant_id=name,
        owner_user_id=name,
        provisioner="local",
        state=RuntimeState.CREATED,
        host="127.0.0.1",
        port=9001,
        working_dir=root / "working",
        secret_dir=root / "secrets",
        backup_dir=root / "backups",
        log_file=root / "logs/app.log",
    )


def _wheel(path: Path) -> Path:
    wheel = path / "paw_isolation_probe-1.0-py3-none-any.whl"
    metadata = "paw_isolation_probe-1.0.dist-info"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "paw_isolation_probe.py",
            "def main():\n    print('runtime-only')\n",
        )
        archive.writestr(
            f"{metadata}/METADATA",
            "Metadata-Version: 2.1\nName: paw-isolation-probe\nVersion: 1.0\n",
        )
        archive.writestr(
            f"{metadata}/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(f"{metadata}/RECORD", "")
        archive.writestr(
            f"{metadata}/entry_points.txt",
            "[console_scripts]\npaw-probe = paw_isolation_probe:main\n",
        )
    return wheel


def test_real_python_pip_shell_and_other_users(tmp_path: Path):
    first = _record(tmp_path, "user with spaces")
    second = _record(tmp_path, "second")
    python = ensure_python_environment(first)
    other_python = ensure_python_environment(second)
    assert ensure_python_environment(first) == python
    environment = dict(os.environ)
    apply_python_environment(first, environment)
    wheel = _wheel(first.working_dir)
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            str(wheel),
        ],
        env=environment,
        check=True,
        capture_output=True,
    )
    info = subprocess.check_output(
        [str(python), "-c", "import sys; print(sys.prefix)"],
        env=environment,
        text=True,
    ).strip()
    assert info == str(environment_root(first))
    shell = ["cmd.exe", "/c"] if os.name == "nt" else ["/bin/sh", "-c"]
    output = subprocess.check_output(
        [*shell, "python -m pip --version && paw-probe"],
        env=environment,
        text=True,
    )
    assert str(environment_root(first)) in output
    assert "runtime-only" in output
    for interpreter in (other_python, Path(sys.executable)):
        result = subprocess.run(
            [str(interpreter), "-c", "import paw_isolation_probe"],
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0


def test_environment_removes_host_overrides_and_merges_path(tmp_path: Path):
    record = _record(tmp_path, "user")
    environment = {
        "Path": "system-tools",
        "CONDA_PREFIX": "host",
        "PYTHONPATH": "other-user",
        "BASH_ENV": "host.sh",
        "PYTHONHOME": "host",
        "ENV": "host.sh",
    }
    apply_python_environment(record, environment)
    assert "Path" not in environment
    assert environment["PATH"].endswith("system-tools")
    assert (
        not {"CONDA_PREFIX", "PYTHONPATH", "BASH_ENV", "ENV"}
        & environment.keys()
    )
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["PIP_USER"] == "0"


def test_concurrent_creation_and_changed_base(tmp_path: Path):
    record = _record(tmp_path, "concurrent")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(ensure_python_environment, [record, record]))
    assert results[0] == results[1]
    marker = environment_root(record) / ".qwenpaw-base.json"
    payload = json.loads(marker.read_text())
    payload["version"] = "old-version"
    marker.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="base changed"):
        ensure_python_environment(record)
    assert results[0].exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Seatbelt")
def test_real_seatbelt_can_install_and_run_user_cli(tmp_path: Path):
    record = _record(tmp_path.resolve(), "sandbox user")
    python = ensure_python_environment(record)
    wheel = _wheel(record.working_dir)
    environment = dict(os.environ)
    apply_python_environment(record, environment)
    environment["HOME"] = str(record.working_dir)
    command = (
        f"python -m pip install --no-index --no-deps {shlex.quote(str(wheel))}"
        f" && paw-probe && python -c "
        + shlex.quote("import sys; print(sys.prefix)")
    )
    launch = MacOSSeatbeltIsolator().prepare(
        record,
        ["/bin/bash", "-c", command],
        environment,
    )
    result = subprocess.run(
        launch.command,
        env=launch.environment,
        cwd=record.working_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "runtime-only" in result.stdout
    assert str(python.parent.parent) in result.stdout


def test_failed_creation_is_retryable(tmp_path: Path, monkeypatch):
    record = _record(tmp_path, "failed")

    def fail(_builder, root):
        Path(root).mkdir()
        raise OSError("ensurepip failed")

    with monkeypatch.context() as context:
        context.setattr(venv.EnvBuilder, "create", fail)
        with pytest.raises(OSError, match="ensurepip failed"):
            ensure_python_environment(record)
    assert not environment_root(record).exists()
    assert ensure_python_environment(record).is_file()


def test_windows_environment_uses_scripts_and_one_path(tmp_path, monkeypatch):
    record = _record(tmp_path, "windows")
    monkeypatch.setattr(
        python_environment,
        "os",
        SimpleNamespace(name="nt", pathsep=";", devnull="nul"),
    )
    environment = {"Path": "C:\\Windows"}
    apply_python_environment(record, environment)
    assert "Scripts/python.exe" in str(
        python_environment.python_executable(record),
    )
    assert environment["PATH"].endswith(";C:\\Windows")
    assert "Path" not in environment
