# -*- coding: utf-8 -*-
"""Tests for fail-closed Pro runtime process isolation."""

import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from qwenpaw.pro.local_driver import LocalProcessRuntimeDriver
from qwenpaw.pro.models import RuntimeRecord, RuntimeState
from qwenpaw.pro.process_isolation import (
    IsolatedLaunch,
    LinuxBubblewrapIsolator,
    ProcessIsolationError,
    ProcessIsolator,
    UnsupportedProcessIsolator,
)


def _record(tmp_path: Path) -> RuntimeRecord:
    root = tmp_path / "runtimes" / "runtime-a"
    for name in ("working", "secrets", "backups", "logs"):
        (root / name).mkdir(parents=True)
    return RuntimeRecord(
        runtime_id="runtime-a",
        tenant_id="tenant-a",
        owner_user_id="user-a",
        driver="local",
        host="127.0.0.1",
        port=9001,
        state=RuntimeState.CREATED,
        working_dir=root / "working",
        secret_dir=root / "secrets",
        backup_dir=root / "backups",
        log_file=root / "logs" / "app.log",
    )


class _RecordingIsolator(ProcessIsolator):
    name = "recording"

    def __init__(self) -> None:
        self.called = False

    def prepare(
        self,
        record: RuntimeRecord,
        command: Sequence[str],
        environment: Mapping[str, str],
    ) -> IsolatedLaunch:
        del record
        self.called = True
        return IsolatedLaunch(
            ["isolation-wrapper", *command],
            dict(environment),
        )


def test_unsupported_platform_fails_closed(tmp_path: Path) -> None:
    isolator = UnsupportedProcessIsolator("required isolation unavailable")

    with pytest.raises(ProcessIsolationError, match="unavailable"):
        isolator.prepare(_record(tmp_path), ["python"], {})


def test_driver_requires_runtime_boundary_token(tmp_path: Path) -> None:
    driver = LocalProcessRuntimeDriver(isolator=_RecordingIsolator())

    with pytest.raises(RuntimeError, match="boundary token"):
        driver.start(_record(tmp_path), {})


def test_driver_preflight_reports_isolation_failure(tmp_path: Path) -> None:
    driver = LocalProcessRuntimeDriver(
        isolator=UnsupportedProcessIsolator("required isolation unavailable"),
    )

    availability = driver.preflight(tmp_path / "preflight")

    assert availability.available is False
    assert availability.reason == "required isolation unavailable"


def test_linux_command_mounts_only_runtime_root_writable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    record = _record(tmp_path)
    isolator = LinuxBubblewrapIsolator("/usr/bin/bwrap")
    monkeypatch.setattr(isolator, "_probe", lambda *args: None)

    launch = isolator.prepare(record, ["python", "-m", "qwenpaw"], {})

    args = launch.command
    bind_index = args.index("--bind")
    assert args[bind_index + 1] == str(record.working_dir.parent)
    assert str(record.working_dir.parent.parent) not in args
    assert "--unshare-pid" in args
    assert "--unshare-user" in args
    assert ["--cap-drop", "ALL"] == args[
        args.index("--cap-drop") : args.index("--cap-drop") + 2
    ]


def test_linux_command_mounts_python_base_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_prefix = tmp_path / "base-python"
    base_bin = base_prefix / "bin"
    base_bin.mkdir(parents=True)
    base_executable = base_bin / "python3.13"
    base_executable.touch()
    (base_bin / "python").symlink_to(base_executable.name)
    venv = tmp_path / "venv"
    venv_bin = venv / "bin"
    venv_bin.mkdir(parents=True)
    venv_executable = venv_bin / "python"
    venv_executable.symlink_to(base_bin / "python")
    monkeypatch.setattr(sys, "executable", str(venv_executable))
    monkeypatch.setattr(sys, "prefix", str(venv))
    monkeypatch.setattr(sys, "base_prefix", str(base_prefix))
    isolator = LinuxBubblewrapIsolator("/usr/bin/bwrap")
    monkeypatch.setattr(isolator, "_probe", lambda *args: None)

    launch = isolator.prepare(
        _record(tmp_path),
        [str(venv_executable), "-m", "qwenpaw"],
        {},
    )

    read_only_mounts = {
        (launch.command[index + 1], launch.command[index + 2])
        for index, value in enumerate(launch.command)
        if value == "--ro-bind"
    }
    assert (str(base_prefix), str(base_prefix)) in read_only_mounts


def test_driver_never_bypasses_injected_isolator(tmp_path: Path) -> None:
    isolator = _RecordingIsolator()
    driver = LocalProcessRuntimeDriver(isolator=isolator)
    record = _record(tmp_path)

    environment = driver.runtime_environment(record, {})
    isolator.prepare(record, ["python"], environment)

    assert isolator.called is True
