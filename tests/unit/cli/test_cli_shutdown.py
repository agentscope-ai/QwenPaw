# -*- coding: utf-8 -*-
from __future__ import annotations

from click.testing import CliRunner

from copaw.cli.main import cli
from copaw.cli import shutdown_cmd as shutdown_cmd_module
from copaw.cli.shutdown_cmd import (
    _find_windows_wrapper_ancestor_pids,
    _terminate_pid,
)


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
        "copaw.cli.shutdown_cmd._find_windows_wrapper_ancestor_pids",
        lambda _pids: set(),
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
        "copaw.cli.shutdown_cmd._find_windows_wrapper_ancestor_pids",
        lambda _pids: set(),
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
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._find_windows_wrapper_ancestor_pids",
        lambda _pids: set(),
    )

    result = CliRunner().invoke(cli, ["shutdown"])

    assert result.exit_code != 0
    assert "No running CoPaw" in result.output


def test_shutdown_command_stops_windows_wrapper_ancestors(monkeypatch) -> None:
    monkeypatch.setattr("copaw.cli.shutdown_cmd.sys.platform", "win32")
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._listening_pids_for_port",
        lambda _port: {24692},
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
        "copaw.cli.shutdown_cmd._find_windows_wrapper_ancestor_pids",
        lambda _pids: {1052},
    )
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._terminate_pid",
        lambda _pid: True,
    )

    result = CliRunner().invoke(cli, ["shutdown"])

    assert result.exit_code == 0
    assert "1052" in result.output
    assert "24692" in result.output


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


def test_terminate_pid_uses_windows_fallback(monkeypatch) -> None:
    calls: list[tuple[int, bool]] = []
    waits = iter([False, False, True])
    fallback_calls: list[int] = []

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
        "copaw.cli.shutdown_cmd._force_terminate_windows_process",
        fallback_calls.append,
    )
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._wait_for_pid_exit",
        lambda _pid, _timeout, _interval: next(waits),
    )

    assert _terminate_pid(17944) is True
    assert calls == [(17944, False), (17944, True)]
    assert fallback_calls == [17944]


def test_pid_exists_uses_windows_snapshot(monkeypatch) -> None:
    monkeypatch.setattr("copaw.cli.shutdown_cmd.sys.platform", "win32")
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._windows_process_snapshot",
        lambda: {29104: (1, "copaw.exe", "copaw app")},
    )

    assert (
        shutdown_cmd_module._pid_exists(  # pylint: disable=protected-access
            29104,
        )
        is True
    )
    assert (
        shutdown_cmd_module._pid_exists(  # pylint: disable=protected-access
            99999,
        )
        is False
    )


def test_find_windows_wrapper_ancestor_pids(monkeypatch) -> None:
    monkeypatch.setattr("copaw.cli.shutdown_cmd.sys.platform", "win32")
    monkeypatch.setattr(
        "copaw.cli.shutdown_cmd._windows_process_snapshot",
        lambda: {
            24692: (1052, "python.exe", "python -m uvicorn copaw.app"),
            1052: (900, "copaw.exe", ""),
            900: (4, "powershell.exe", "powershell"),
        },
    )

    assert _find_windows_wrapper_ancestor_pids({24692}) == {1052}


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
        (
            4242,
            shutdown_cmd_module._SIGTERM,  # pylint: disable=protected-access
        ),
        (
            4242,
            shutdown_cmd_module._SIGKILL,  # pylint: disable=protected-access
        ),
    ]
