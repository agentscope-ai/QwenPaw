# -*- coding: utf-8 -*-
"""Tests for fail-closed Hub runtime process isolation."""

import sys
import threading
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from qwenpaw.hub.local_provisioner import LocalProcessRuntimeProvisioner
from qwenpaw.hub.models import RuntimeRecord, RuntimeState
from qwenpaw.hub.process_isolation import (
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
        provisioner="local",
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


def test_provisioner_requires_runtime_boundary_token(tmp_path: Path) -> None:
    provisioner = LocalProcessRuntimeProvisioner(isolator=_RecordingIsolator())

    with pytest.raises(RuntimeError, match="boundary token"):
        provisioner.start(_record(tmp_path), {})


def test_provisioner_preflight_reports_isolation_failure(
    tmp_path: Path,
) -> None:
    provisioner = LocalProcessRuntimeProvisioner(
        isolator=UnsupportedProcessIsolator("required isolation unavailable"),
    )

    availability = provisioner.preflight(tmp_path / "preflight")

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
    assert ("/etc", "/etc") not in {
        (args[index + 1], args[index + 2])
        for index, value in enumerate(args)
        if value == "--ro-bind"
    }
    assert "--unshare-pid" in args
    assert "--unshare-user" in args
    assert ["--cap-drop", "ALL"] == args[
        args.index("--cap-drop") : args.index("--cap-drop") + 2
    ]


def test_linux_command_mounts_resolver_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = Path("/etc/resolv.conf").resolve()
    if not resolver.exists():
        pytest.skip("resolver configuration is unavailable")
    isolator = LinuxBubblewrapIsolator("/usr/bin/bwrap")
    monkeypatch.setattr(isolator, "_probe", lambda *args: None)

    launch = isolator.prepare(
        _record(tmp_path),
        ["python", "-m", "qwenpaw"],
        {},
    )

    read_only_mounts = {
        (launch.command[index + 1], launch.command[index + 2])
        for index, value in enumerate(launch.command)
        if value == "--ro-bind"
    }
    assert (str(resolver), str(resolver)) in read_only_mounts


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


def test_linux_command_never_mounts_pythonpath(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted_path = tmp_path / "trusted-source"
    trusted_path.mkdir()
    other_tenant = tmp_path / "runtimes" / "runtime-b"
    other_tenant.mkdir(parents=True)
    monkeypatch.setenv("PYTHONPATH", str(trusted_path))
    isolator = LinuxBubblewrapIsolator("/usr/bin/bwrap")
    monkeypatch.setattr(isolator, "_probe", lambda *args: None)

    launch = isolator.prepare(
        _record(tmp_path),
        ["python", "-m", "qwenpaw"],
        {"PYTHONPATH": f"{Path('/')}:{other_tenant}"},
    )

    read_only_sources = {
        launch.command[index + 1]
        for index, value in enumerate(launch.command)
        if value == "--ro-bind"
    }
    assert str(trusted_path.resolve()) not in read_only_sources
    assert str(Path("/")) not in read_only_sources
    assert str(other_tenant.resolve()) not in read_only_sources


def test_provisioner_never_bypasses_injected_isolator(tmp_path: Path) -> None:
    isolator = _RecordingIsolator()
    provisioner = LocalProcessRuntimeProvisioner(isolator=isolator)
    record = _record(tmp_path)

    environment = provisioner.runtime_environment(record, {})
    isolator.prepare(record, ["python"], environment)

    assert isolator.called is True


def test_local_readiness_ignores_optional_integration_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provisioner = LocalProcessRuntimeProvisioner(
        isolator=_RecordingIsolator(),
    )
    requests: list[urllib.request.Request] = []

    class _Process:
        @staticmethod
        def poll() -> None:
            return None

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            del args

    def urlopen(
        request: urllib.request.Request,
        timeout: int,
    ) -> _Response:
        del timeout
        requests.append(request)
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    provisioner._wait_until_ready(  # pylint: disable=protected-access
        _record(tmp_path),
        _Process(),
        "runtime-token",
    )

    assert requests[0].full_url == "http://127.0.0.1:9001/api/version"
    assert requests[0].get_header("X-qwenpaw-runtime-token") == (
        "runtime-token"
    )


def test_runtime_parent_thread_survives_request_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolator = _RecordingIsolator()
    provisioner = LocalProcessRuntimeProvisioner(isolator=isolator)
    launcher_threads: list[threading.Thread] = []
    results: list[RuntimeRecord] = []

    class _Process:
        pid = 12345

        @staticmethod
        def poll() -> None:
            return None

        @staticmethod
        def wait(timeout: float) -> int:
            del timeout
            return 0

    def popen(*args, **kwargs):
        del args, kwargs
        launcher_threads.append(threading.current_thread())
        return _Process()

    monkeypatch.setattr(
        "qwenpaw.hub.local_provisioner.subprocess.Popen",
        popen,
    )
    monkeypatch.setattr(
        "qwenpaw.hub.local_provisioner.os.killpg",
        lambda *_: None,
    )
    monkeypatch.setattr(provisioner, "_wait_until_ready", lambda *_: None)

    request_worker = threading.Thread(
        target=lambda: results.append(
            provisioner.start(
                _record(tmp_path),
                {"QWENPAW_RUNTIME_INTERNAL_TOKEN": "secret"},
            ),
        ),
    )
    request_worker.start()
    request_worker.join()

    assert results[0].state is RuntimeState.RUNNING
    assert launcher_threads[0] is not request_worker
    assert launcher_threads[0].is_alive()

    provisioner.close()

    assert not launcher_threads[0].is_alive()
