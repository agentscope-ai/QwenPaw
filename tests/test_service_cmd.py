# -*- coding: utf-8 -*-
import subprocess
from pathlib import Path

from click.testing import CliRunner

from copaw.cli.main import cli
from copaw.cli.service_cmd import (
    _launchd_restart,
    _launchd_start,
    _launchd_stop,
    _parse_launchctl_print,
    _probe_version,
    _parse_systemctl_show,
    build_launchd_plist,
    build_systemd_unit,
)


def test_build_launchd_plist_contains_core_fields() -> None:
    plist = build_launchd_plist(
        label="ai.copaw.app",
        program_arguments=["/usr/bin/python3", "-m", "copaw", "app"],
        working_directory=Path("/tmp/copaw"),
        environment={
            "COPAW_WORKING_DIR": "/tmp/copaw",
            "COPAW_LOG_LEVEL": "info",
        },
        stdout_path=Path("/tmp/copaw/logs/service.log"),
        stderr_path=Path("/tmp/copaw/logs/service.err.log"),
    )
    assert "<key>Label</key>" in plist
    assert "ai.copaw.app" in plist
    assert "<key>ProgramArguments</key>" in plist
    assert "<string>copaw</string>" in plist
    assert "<key>EnvironmentVariables</key>" in plist
    assert "COPAW_WORKING_DIR" in plist
    assert "COPAW_LOG_LEVEL" in plist
    assert "<key>KeepAlive</key>" in plist
    assert "service.err.log" in plist


def test_build_systemd_unit_contains_exec_and_env() -> None:
    unit = build_systemd_unit(
        description="CoPaw application service",
        program_arguments=[
            "/usr/bin/python3",
            "-m",
            "copaw",
            "app",
            "--port",
            "8088",
        ],
        working_directory=Path("/opt/copaw"),
        environment={
            "COPAW_WORKING_DIR": "/opt/copaw",
            "COPAW_LOG_LEVEL": "info",
        },
    )
    assert "[Service]" in unit
    assert "ExecStart=" in unit
    assert " -m copaw app --port 8088" in unit
    assert 'Environment="COPAW_WORKING_DIR=/opt/copaw"' in unit
    assert 'Environment="COPAW_LOG_LEVEL=info"' in unit
    assert "Restart=always" in unit


def test_parse_launchctl_print_detects_running_and_pid() -> None:
    output = """
    state = running
    pid = 9527
    """
    running, pid, state = _parse_launchctl_print(output)
    assert running is True
    assert pid == 9527
    assert state == "running"


def test_parse_launchctl_print_handles_pid_then_active_state() -> None:
    output = """
    pid = 1024
    state = active
    """
    running, pid, state = _parse_launchctl_print(output)
    assert running is True
    assert pid == 1024
    assert state == "active"


def test_parse_launchctl_print_spawn_scheduled_not_running() -> None:
    output = """
    state = spawn scheduled
    """
    running, pid, state = _parse_launchctl_print(output)
    assert running is False
    assert pid is None
    assert state == "spawn scheduled"


def test_parse_launchctl_print_waiting_with_zero_pid_is_not_running() -> None:
    output = """
    state = waiting
    pid = 0
    """
    running, pid, state = _parse_launchctl_print(output)
    assert running is False
    assert pid is None
    assert state == "waiting"


def test_parse_launchctl_print_malformed_output_is_safe() -> None:
    running, pid, state = _parse_launchctl_print("invalid output")
    assert running is False
    assert pid is None
    assert state == ""


def test_parse_systemctl_show_detects_running_and_pid() -> None:
    output = """
    ActiveState=active
    MainPID=1234
    """
    running, pid, state = _parse_systemctl_show(output)
    assert running is True
    assert pid == 1234
    assert state == "active"


def test_parse_systemctl_show_inactive_with_zero_pid() -> None:
    output = """
    ActiveState=inactive
    MainPID=0
    """
    running, pid, state = _parse_systemctl_show(output)
    assert running is False
    assert pid is None
    assert state == "inactive"


def test_parse_systemctl_show_malformed_output_is_safe() -> None:
    running, pid, state = _parse_systemctl_show("something wrong")
    assert running is False
    assert pid is None
    assert state == ""


def test_daemon_alias_exposes_service_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["daemon", "--help"])
    assert result.exit_code == 0
    assert "install" in result.output
    assert "restart" in result.output


def test_launchd_stop_uses_service_target_bootout(
    monkeypatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(
        cmd: list[str],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        _ = check
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("copaw.cli.service_cmd._run_command", fake_run)
    monkeypatch.setattr(
        "copaw.cli.service_cmd._launchd_label",
        lambda: "ai.copaw.app",
    )
    monkeypatch.setattr(
        "copaw.cli.service_cmd._launchd_domain",
        lambda: "gui/501",
    )
    _launchd_stop()

    assert commands[0] == ["launchctl", "bootout", "gui/501/ai.copaw.app"]


def test_probe_version_bypasses_proxy_for_localhost(monkeypatch) -> None:
    called = {"opener": False, "urlopen": False}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b'{"version":"0.0.5"}'

    class _Opener:
        def open(self, url: str, timeout: float):
            called["opener"] = True
            assert url.endswith("/api/version")
            assert timeout == 2.0
            return _Resp()

    def fake_build_opener(*_args, **_kwargs):
        return _Opener()

    def fake_urlopen(*_args, **_kwargs):
        called["urlopen"] = True
        raise AssertionError("urlopen should not be used for localhost probes")

    monkeypatch.setattr(
        "copaw.cli.service_cmd.build_opener",
        fake_build_opener,
    )
    monkeypatch.setattr("copaw.cli.service_cmd.urlopen", fake_urlopen)
    ok, message = _probe_version("127.0.0.1", 8088, 2.0)
    assert ok is True
    assert "version=0.0.5" in message
    assert called["opener"] is True
    assert called["urlopen"] is False


def test_probe_version_retries_until_success(monkeypatch) -> None:
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b'{"version":"0.1.0"}'

    attempts = {"count": 0}

    class _Opener:
        def open(self, _url: str, timeout: float):
            _ = timeout
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise OSError("Connection refused")
            return _Resp()

    monkeypatch.setattr(
        "copaw.cli.service_cmd.build_opener",
        lambda *a, **k: _Opener(),
    )
    monkeypatch.setattr("copaw.cli.service_cmd.time.sleep", lambda _s: None)

    ok, message = _probe_version("127.0.0.1", 8088, 2.0)
    assert ok is True
    assert "version=0.1.0" in message
    assert attempts["count"] == 3


def test_probe_version_maps_wildcard_host_to_loopback(monkeypatch) -> None:
    seen = {"url": ""}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b'{"version":"0.2.0"}'

    class _Opener:
        def open(self, url: str, timeout: float):
            _ = timeout
            seen["url"] = url
            return _Resp()

    monkeypatch.setattr(
        "copaw.cli.service_cmd.build_opener",
        lambda *a, **k: _Opener(),
    )

    ok, message = _probe_version("0.0.0.0", 8088, 2.0)
    assert ok is True
    assert "version=0.2.0" in message
    assert seen["url"].startswith("http://127.0.0.1:8088/")


def test_probe_version_brackets_ipv6_host(monkeypatch) -> None:
    seen = {"url": ""}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b'{"version":"0.2.0"}'

    class _Opener:
        def open(self, url: str, timeout: float):
            _ = timeout
            seen["url"] = url
            return _Resp()

    monkeypatch.setattr(
        "copaw.cli.service_cmd.build_opener",
        lambda *a, **k: _Opener(),
    )

    ok, message = _probe_version("::1", 8088, 2.0)
    assert ok is True
    assert "version=0.2.0" in message
    assert seen["url"].startswith("http://[::1]:8088/")


def test_build_systemd_unit_escapes_control_chars_in_env() -> None:
    unit = build_systemd_unit(
        description="CoPaw application service",
        program_arguments=["/usr/bin/python3", "-m", "copaw", "app"],
        working_directory=Path("/opt/copaw"),
        environment={"COPAW_TOKEN": 'line1\nline2\rline3\t"a"'},
    )
    assert 'Environment="COPAW_TOKEN=line1\\nline2\\rline3\\t\\"a\\""' in unit


def test_launchd_start_retries_bootstrap_then_succeeds(
    monkeypatch,
    tmp_path,
) -> None:
    commands: list[list[str]] = []
    bootstrap_calls = {"count": 0}

    def fake_run(
        cmd: list[str],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        _ = check
        commands.append(cmd)
        if cmd[:3] == ["launchctl", "kickstart", "-k"]:
            if len(commands) == 1:
                return subprocess.CompletedProcess(cmd, 3, "", "not loaded")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:2] == ["launchctl", "bootstrap"]:
            bootstrap_calls["count"] += 1
            if bootstrap_calls["count"] == 1:
                return subprocess.CompletedProcess(
                    cmd,
                    5,
                    "",
                    "Input/output error",
                )
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("copaw.cli.service_cmd._run_command", fake_run)
    monkeypatch.setattr(
        "copaw.cli.service_cmd._launchd_label",
        lambda: "ai.copaw.app",
    )
    monkeypatch.setattr(
        "copaw.cli.service_cmd._launchd_domain",
        lambda: "gui/501",
    )
    monkeypatch.setattr(
        "copaw.cli.service_cmd._launchd_plist_path",
        lambda _label: tmp_path / "ai.copaw.app.plist",
    )
    (tmp_path / "ai.copaw.app.plist").write_text("<plist/>", encoding="utf-8")
    monkeypatch.setattr("copaw.cli.service_cmd.time.sleep", lambda _s: None)

    _launchd_start()

    assert bootstrap_calls["count"] == 2
    assert commands[0] == [
        "launchctl",
        "kickstart",
        "-k",
        "gui/501/ai.copaw.app",
    ]


def test_launchd_restart_uses_kickstart(monkeypatch, tmp_path) -> None:
    commands: list[list[str]] = []

    def fake_run(
        cmd: list[str],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        _ = check
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("copaw.cli.service_cmd._run_command", fake_run)
    monkeypatch.setattr(
        "copaw.cli.service_cmd._launchd_label",
        lambda: "ai.copaw.app",
    )
    monkeypatch.setattr(
        "copaw.cli.service_cmd._launchd_domain",
        lambda: "gui/501",
    )
    monkeypatch.setattr(
        "copaw.cli.service_cmd._launchd_plist_path",
        lambda _label: tmp_path / "ai.copaw.app.plist",
    )
    (tmp_path / "ai.copaw.app.plist").write_text("<plist/>", encoding="utf-8")

    _launchd_restart()

    assert commands[0] == [
        "launchctl",
        "kickstart",
        "-k",
        "gui/501/ai.copaw.app",
    ]
