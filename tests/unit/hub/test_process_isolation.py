# -*- coding: utf-8 -*-
"""Tests for fail-closed Hub runtime process isolation."""

import mimetypes
import subprocess
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
    MacOSSeatbeltIsolator,
    ProcessIsolationError,
    ProcessIsolator,
    UnsupportedProcessIsolator,
)
from tests.unit.hub.factories import runtime_record as _record


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


class _WindowsRecordingIsolator(_RecordingIsolator):
    name = "windows-appcontainer"

    def __init__(self) -> None:
        super().__init__()
        self.command: list[str] = []
        self.process = _RuntimeProcess()

    def prepare(
        self,
        record: RuntimeRecord,
        command: Sequence[str],
        environment: Mapping[str, str],
    ) -> IsolatedLaunch:
        del record
        self.called = True
        self.command = list(command)
        return IsolatedLaunch(list(command), dict(environment))

    def launch(self, *args, **kwargs) -> "_RuntimeProcess":
        del args, kwargs
        return self.process


class _RuntimeProcess:
    pid = 12345

    def __init__(self) -> None:
        self.running = True

    def poll(self) -> int | None:
        return None if self.running else 0

    def terminate(self) -> None:
        self.running = False

    def kill(self) -> None:
        self.running = False

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.running = False
        return 0


class _TunnelBroker:
    instances: list["_TunnelBroker"] = []

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.control_port = 9100
        self.token = "tunnel-token"
        self.started = False
        self.closed = False
        self.instances.append(self)

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed = True


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
    tmp_index = next(
        index
        for index, value in enumerate(args)
        if value == "--tmpfs" and args[index + 1] == "/tmp"
    )
    read_only_sources = {
        args[index + 1]
        for index, value in enumerate(args)
        if value == "--ro-bind"
    }
    repository = Path(__file__).parents[3]
    assert tmp_index < bind_index
    assert args[bind_index + 1] == str(record.working_dir.parent)
    assert str(record.working_dir.parent.parent) not in args
    assert str(repository / "packages" / "qwenpawmail-mcp" / "src") in (
        read_only_sources
    )
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


def test_linux_command_mounts_resolver_at_standard_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = Path("/etc/resolv.conf")
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


def test_macos_profile_does_not_allow_global_file_reads(
    tmp_path: Path,
) -> None:
    record = _record(tmp_path)
    isolator = MacOSSeatbeltIsolator()

    profile = isolator._profile(  # pylint: disable=protected-access
        record,
    )
    runtime_root = isolator._escape(  # pylint: disable=protected-access
        record.working_dir.parent,
    )

    assert "\n(allow file-read*)\n" not in f"\n{profile}\n"
    assert f'(allow file-read* (subpath "{runtime_root}"))' in profile


def test_macos_profile_allows_system_mime_types(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mime_types = tmp_path / "system" / "mime.types"
    mime_types.parent.mkdir()
    mime_types.write_text("text/plain txt", encoding="utf-8")
    monkeypatch.setattr(mimetypes, "knownfiles", [str(mime_types)])
    isolator = MacOSSeatbeltIsolator()

    profile = isolator._profile(  # pylint: disable=protected-access
        _record(tmp_path),
    )
    allowed_path = isolator._escape(  # pylint: disable=protected-access
        mime_types,
    )

    assert f'(allow file-read* (subpath "{allowed_path}"))' in profile


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="Seatbelt is only available on macOS.",
)
def test_macos_seatbelt_blocks_reads_outside_allowlist(
    tmp_path: Path,
) -> None:
    sandbox_exec = Path("/usr/bin/sandbox-exec")
    if not sandbox_exec.is_file():
        pytest.skip("sandbox-exec is unavailable")
    record = _record(tmp_path)
    allowed = record.working_dir / "allowed.txt"
    allowed.write_text("allowed", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside-secret", encoding="utf-8")
    profile_path = record.secret_dir / "runtime-test.sb"
    profile_path.write_text(
        MacOSSeatbeltIsolator()._profile(  # pylint: disable=protected-access
            record,
        ),
        encoding="utf-8",
    )

    allowed_result = subprocess.run(
        [
            str(sandbox_exec),
            "-f",
            str(profile_path),
            "/bin/cat",
            str(allowed),
        ],
        capture_output=True,
        text=True,
        cwd=record.working_dir,
        check=False,
    )
    blocked_result = subprocess.run(
        [str(sandbox_exec), "-f", str(profile_path), "/bin/cat", str(outside)],
        capture_output=True,
        text=True,
        cwd=record.working_dir,
        check=False,
    )

    assert allowed_result.returncode == 0
    assert allowed_result.stdout == "allowed"
    assert blocked_result.returncode != 0


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="Seatbelt is only available on macOS.",
)
def test_macos_seatbelt_real_preflight(tmp_path: Path) -> None:
    provisioner = LocalProcessRuntimeProvisioner(
        isolator=MacOSSeatbeltIsolator(),
    )

    availability = provisioner.preflight(tmp_path / "preflight")

    provisioner.close()
    assert availability.available, availability.reason


def test_provisioner_launches_through_injected_isolator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolator = _RecordingIsolator()
    provisioner = LocalProcessRuntimeProvisioner(isolator=isolator)
    monkeypatch.setattr(
        isolator,
        "launch",
        lambda *_: _RuntimeProcess(),
    )
    monkeypatch.setattr(provisioner, "_wait_until_ready", lambda *_: None)

    started = provisioner.start(
        _record(tmp_path),
        {"QWENPAW_RUNTIME_INTERNAL_TOKEN": "secret"},
    )

    assert isolator.called is True
    assert started.state is RuntimeState.RUNNING
    provisioner.close()


def test_windows_runtime_uses_outbound_reverse_tunnel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _TunnelBroker.instances.clear()
    isolator = _WindowsRecordingIsolator()
    provisioner = LocalProcessRuntimeProvisioner(isolator=isolator)
    monkeypatch.setattr(
        "qwenpaw.hub.local_provisioner.WindowsReverseTunnelBroker",
        _TunnelBroker,
    )
    monkeypatch.setattr(provisioner, "_wait_until_ready", lambda *_: None)

    started = provisioner.start(
        _record(tmp_path),
        {"QWENPAW_RUNTIME_INTERNAL_TOKEN": "secret"},
    )

    command = isolator.command
    separator = command.index("--")
    assert command[command.index("-m") + 1] == (
        "qwenpaw.hub.windows_runtime_bridge"
    )
    assert command[command.index("--control-port") + 1] == "9100"
    assert command[command.index("--token") + 1] == "tunnel-token"
    assert command[separator + 1 : separator + 4] == [
        sys.executable,
        "-m",
        "qwenpaw",
    ]
    assert command[command.index("--host", separator) + 1] == "127.0.0.1"
    assert started.port == 9001
    assert _TunnelBroker.instances[0].started is True

    isolator.process.running = False
    provisioner.close()

    assert _TunnelBroker.instances[0].closed is True


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

        @staticmethod
        def terminate() -> None:
            pass

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
        raising=False,
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
