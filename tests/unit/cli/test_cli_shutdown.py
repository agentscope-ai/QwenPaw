# -*- coding: utf-8 -*-
from __future__ import annotations

from click.testing import CliRunner

from copaw.cli.main import cli
from copaw.cli import shutdown_cmd as shutdown_cmd_module
from copaw.cli.shutdown_cmd import _terminate_pid


def test_shutdown_command_stops_backend_and_frontend(monkeypatch) -> None:
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._listening_pids_for_port",
        lambda _port: {1001},
    )
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._find_frontend_dev_pids",
        lambda: {2002},
    )
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._find_desktop_wrapper_pids",
        set,
    )
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._terminate_pid",
        lambda _pid: True,
    )

    result = CliRunner().invoke(cli, ["shutdown"])

    assert result.exit_code == 0
    assert "1001" in result.output
    assert "2002" in result.output


def test_shutdown_command_reports_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._listening_pids_for_port",
        lambda _port: {1001},
    )
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._find_frontend_dev_pids",
        set,
    )
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._find_desktop_wrapper_pids",
        set,
    )
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._terminate_pid",
        lambda _pid: False,
    )

    result = CliRunner().invoke(cli, ["shutdown"])

    assert result.exit_code != 0
    assert "Failed to shutdown process" in result.output


def test_shutdown_command_reports_nothing_found(monkeypatch) -> None:
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._listening_pids_for_port",
        lambda _port: set(),
    )
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._find_frontend_dev_pids",
        set,
    )
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._find_desktop_wrapper_pids",
        set,
    )

    result = CliRunner().invoke(cli, ["shutdown"])

    assert result.exit_code != 0
    assert "No running CoPaw" in result.output


def test_terminate_pid_force_kills_on_windows(monkeypatch) -> None:
    calls: list[tuple[int, bool]] = []
    waits = iter([False, True])

    monkeypatch.setattr("copaw.cli.shutdown_cmd.sys.platform", "win32")
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._pid_exists",
        lambda _pid: True,
    )
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._terminate_process_tree_windows",
        lambda pid, force=False: calls.append((pid, force)),
    )
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._wait_for_pid_exit",
        lambda _pid, _timeout, _interval: next(waits),
    )

    assert _terminate_pid(17944) is True
    assert calls == [(17944, False), (17944, True)]


def test_terminate_pid_force_kills_on_unix(monkeypatch) -> None:
    calls: list[tuple[int, object]] = []
    waits = iter([False, True])

    monkeypatch.setattr("copaw.cli.shutdown_cmd.sys.platform", "darwin")
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._pid_exists",
        lambda _pid: True,
    )
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._signal_process_tree_unix",
        lambda pid, sig: calls.append((pid, sig)),
    )
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._wait_for_pid_exit",
        lambda _pid, _timeout, _interval: next(waits),
    )

    assert _terminate_pid(4242) is True
    assert calls == [
        (4242, shutdown_cmd_module._SIGTERM),
        (4242, shutdown_cmd_module._SIGKILL),
    ]
