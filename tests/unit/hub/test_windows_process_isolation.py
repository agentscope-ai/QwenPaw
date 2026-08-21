# -*- coding: utf-8 -*-
"""Tests for Windows AppContainer Hub runtime isolation."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import IO, Any

import pytest

from qwenpaw.hub.local_provisioner import LocalProcessRuntimeProvisioner
from qwenpaw.hub.process_isolation import (
    IsolatedLaunch,
    ProcessIsolationError,
)
from qwenpaw.hub.windows_process_isolation import (
    WindowsAppContainerIsolator,
)
from tests.unit.hub.factories import runtime_record as _record


class _Process:
    pid = 42

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        pass

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0


class _Sandbox:
    instances: list["_Sandbox"] = []

    def __init__(self, config: Any) -> None:
        self.config = config
        self.container_name = "qwenpaw_runtime_a"
        self.container_sid = "S-1-15-2-123"
        self.stopped = False
        self.spawned: tuple[list[str], str, dict[str, str]] | None = None
        self.instances.append(self)

    async def __aenter__(self) -> "_Sandbox":
        return self

    async def stop(self) -> None:
        self.stopped = True

    def spawn_process(
        self,
        command: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        log_handle: IO[str],
    ) -> _Process:
        del log_handle
        self.spawned = (command, cwd, env)
        return _Process()


def _mock_windows_boundary(
    monkeypatch: pytest.MonkeyPatch,
    isolator: WindowsAppContainerIsolator,
) -> list[tuple[str, bool]]:
    _Sandbox.instances.clear()
    loopback_calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        "qwenpaw.hub.windows_process_isolation.is_windows_admin",
        lambda: True,
    )
    monkeypatch.setattr(
        "qwenpaw.hub.windows_process_isolation.WindowsAppContainerSandbox",
        _Sandbox,
    )

    def set_loopback(
        container_sid: str,
        *,
        enabled: bool,
        check: bool = True,
    ) -> None:
        del check
        loopback_calls.append((container_sid, enabled))

    monkeypatch.setattr(isolator, "_set_loopback_exemption", set_loopback)
    monkeypatch.setattr(isolator, "_probe", lambda *_args: None)
    return loopback_calls


def test_windows_boundary_is_fail_closed_without_admin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        "qwenpaw.hub.windows_process_isolation.is_windows_admin",
        lambda: False,
    )
    isolator = WindowsAppContainerIsolator()

    with pytest.raises(ProcessIsolationError, match="administrator"):
        isolator.prepare(_record(tmp_path), ["python", "-m", "qwenpaw"], {})


def test_windows_boundary_uses_private_writable_mounts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record(tmp_path)
    isolator = WindowsAppContainerIsolator()
    loopback_calls = _mock_windows_boundary(monkeypatch, isolator)

    launch = isolator.prepare(record, ["python", "-m", "qwenpaw"], {})

    sandbox = _Sandbox.instances[0]
    writable = {
        Path(mount.path) for mount in sandbox.config.mounts if mount.writable
    }
    assert sandbox.config.allow_read_all is False
    assert sandbox.config.network_allow == ["*"]
    assert writable == {
        record.working_dir / "tmp",
        record.working_dir / "appdata" / "roaming",
        record.working_dir / "appdata" / "local",
        record.secret_dir,
        record.backup_dir,
        record.log_file.parent,
    }
    assert launch == IsolatedLaunch(["python", "-m", "qwenpaw"], {})
    assert loopback_calls == [("S-1-15-2-123", True)]

    isolator.release(record.runtime_id)

    assert sandbox.stopped is True
    assert loopback_calls == [
        ("S-1-15-2-123", True),
        ("S-1-15-2-123", False),
    ]


def test_windows_boundary_launches_inside_prepared_sandbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record(tmp_path)
    isolator = WindowsAppContainerIsolator()
    _mock_windows_boundary(monkeypatch, isolator)
    launch = isolator.prepare(record, ["python", "-m", "qwenpaw"], {})

    with record.log_file.open("a", encoding="utf-8") as log_handle:
        process = isolator.launch(record, launch, log_handle)

    sandbox = _Sandbox.instances[0]
    assert process.pid == 42
    assert sandbox.spawned == (
        ["python", "-m", "qwenpaw"],
        str(record.working_dir),
        {},
    )
    isolator.release(record.runtime_id)


def test_windows_probe_timeout_terminates_job_tree(tmp_path: Path) -> None:
    record = _record(tmp_path)

    class _TimeoutProcess(_Process):
        terminated = False
        waits = 0

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("probe", 10)
            return 1

    class _TimeoutSandbox:
        process = _TimeoutProcess()

        def spawn_process(self, *args: Any, **kwargs: Any) -> _Process:
            del args, kwargs
            return self.process

    sandbox = _TimeoutSandbox()

    with pytest.raises(ProcessIsolationError, match="timed out"):
        # pylint: disable-next=protected-access
        WindowsAppContainerIsolator._run_probe(
            sandbox,  # type: ignore[arg-type]
            record,
            "pass",
            {},
        )

    assert sandbox.process.terminated is True
    assert sandbox.process.waits == 2


@pytest.mark.skipif(
    sys.platform != "win32"
    or os.environ.get("QWENPAW_WINDOWS_APPCONTAINER_E2E") != "1",
    reason="requires the elevated GitHub Windows AppContainer runner",
)
def test_windows_appcontainer_real_preflight(tmp_path: Path) -> None:
    provisioner = LocalProcessRuntimeProvisioner(
        isolator=WindowsAppContainerIsolator(),
    )

    availability = provisioner.preflight(tmp_path / "preflight")
    provisioner.close()

    assert availability.available, availability.reason
