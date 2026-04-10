# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import click

from .process_utils import (
    _is_qwenpaw_wrapper_process,
    _process_table,
    _windows_process_snapshot,
)


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CONSOLE_DIR = (_PROJECT_ROOT / "console").resolve()
_SIGTERM = signal.SIGTERM
_SIGKILL = getattr(signal, "SIGKILL", _SIGTERM)


def _backend_port(ctx: click.Context, port: Optional[int]) -> int:
    """Resolve backend port from explicit option or global CLI context."""
    if port is not None:
        return port
    return int((ctx.obj or {}).get("port", 8088))


def _listening_pids_for_port(port: int) -> set[int]:
    """Return PIDs currently listening on the given TCP port."""
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return set()

        pids: set[int] = set()
        suffix = f":{port}"
        for line in (result.stdout or "").splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            local_addr = parts[1]
            state = parts[3].upper()
            if not local_addr.endswith(suffix) or state != "LISTENING":
                continue
            try:
                pids.add(int(parts[4]))
            except ValueError:
                continue
        return pids

    commands = (
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        ["fuser", f"{port}/tcp"],
    )
    for command in commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue

        pids = {
            int(token)
            for token in (result.stdout or "").split()
            if token.isdigit()
        }
        if pids:
            return pids
    return set()


def _find_frontend_dev_pids() -> set[int]:
    """Find Vite dev-server processes for this repository's console app."""
    console_dir = str(_CONSOLE_DIR).lower()
    matches: set[int] = set()
    for pid, command in _process_table():
        lowered = command.lower()
        if "vite" in lowered and console_dir in lowered:
            matches.add(pid)
            continue
        if "qwenpaw-console" in lowered and (
            "npm" in lowered
            or "pnpm" in lowered
            or "yarn" in lowered
            or "node" in lowered
        ):
            matches.add(pid)
    return matches


def _find_desktop_wrapper_pids() -> set[int]:
    """Find `qwenpaw desktop` wrapper processes for this project."""
    matches: set[int] = set()
    patterns = (
        " -m qwenpaw desktop",
        " qwenpaw desktop",
        "__main__.py desktop",
    )
    for pid, command in _process_table():
        lowered = f" {command.lower()}"
        if any(pattern in lowered for pattern in patterns):
            matches.add(pid)
    return matches


def _find_windows_wrapper_ancestor_pids(pids: set[int]) -> set[int]:
    """Find QwenPaw wrapper/supervisor ancestors for Windows backend PIDs."""
    if sys.platform != "win32" or not pids:
        return set()

    snapshot = _windows_process_snapshot()
    matches: set[int] = set()
    for pid in pids:
        visited: set[int] = set()
        current_pid = pid
        while True:
            info = snapshot.get(current_pid)
            if info is None:
                break

            parent_pid = info[0]
            if parent_pid in (None, 0) or parent_pid in visited:
                break
            visited.add(parent_pid)

            parent_info = snapshot.get(parent_pid)
            if parent_info is None:
                break

            if _is_qwenpaw_wrapper_process(parent_info[1], parent_info[2]):
                matches.add(parent_pid)

            current_pid = parent_pid
    return matches


def _child_pids_unix(pid: int) -> set[int]:
    """Recursively collect child PIDs for Unix-like systems."""
    children: set[int] = set()
    stack = [pid]
    while stack:
        current = stack.pop()
        try:
            result = subprocess.run(
                ["pgrep", "-P", str(current)],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        for token in (result.stdout or "").split():
            if not token.isdigit():
                continue
            child = int(token)
            if child in children:
                continue
            children.add(child)
            stack.append(child)
    return children


def _pid_exists(pid: int) -> bool:
    """Return whether the PID still exists."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return pid in _windows_process_snapshot()
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _wait_for_pid_exit(
    pid: int,
    timeout_sec: float,
    interval_sec: float,
) -> bool:
    """Wait until a PID exits within the given timeout."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if not _pid_exists(pid):
            return True
        time.sleep(interval_sec)
    return not _pid_exists(pid)


def _signal_process_tree_unix(pid: int, sig: signal.Signals) -> None:
    """Send a signal to a Unix process and its descendants."""
    descendants = sorted(_child_pids_unix(pid), reverse=True)
    for child_pid in descendants:
        try:
            os.kill(child_pid, sig)
        except OSError:
            continue
    try:
        os.kill(pid, sig)
    except OSError:
        pass


def _terminate_process_tree_windows(pid: int, force: bool = False) -> None:
    """Terminate a Windows process tree."""
    command = ["taskkill", "/T", "/PID", str(pid)]
    if force:
        command.insert(1, "/F")
    try:
        subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _force_terminate_windows_process(pid: int) -> None:
    """Force terminate a Windows process as a fallback."""
    commands = (
        [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "$ErrorActionPreference='SilentlyContinue'; "
                f"Stop-Process -Id {pid} -Force"
            ),
        ],
        ["taskkill", "/F", "/PID", str(pid)],
    )
    for command in commands:
        try:
            subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue


def _terminate_pid(pid: int, timeout_sec: float = 5.0) -> bool:
    """Terminate a process tree gracefully, then force kill if needed."""
    if not _pid_exists(pid):
        return True

    if sys.platform == "win32":
        _terminate_process_tree_windows(pid)
    else:
        _signal_process_tree_unix(pid, _SIGTERM)

    if _wait_for_pid_exit(pid, timeout_sec, 0.2):
        return True

    if sys.platform == "win32":
        _terminate_process_tree_windows(pid, force=True)
        if _wait_for_pid_exit(pid, 2.0, 0.1):
            return True
        _force_terminate_windows_process(pid)
    else:
        _signal_process_tree_unix(pid, _SIGKILL)

    return _wait_for_pid_exit(pid, 2.0, 0.1)


def _stop_pid_set(pids: set[int]) -> tuple[list[int], list[int]]:
    """Stop a set of PIDs and return (stopped, failed)."""
    stopped: list[int] = []
    failed: list[int] = []
    for pid in sorted(pids):
        if _terminate_pid(pid):
            stopped.append(pid)
        else:
            failed.append(pid)
    return stopped, failed


@click.command(
    "shutdown",
    help="Force stop the running QwenPaw app processes.",
)
@click.option(
    "--port",
    default=None,
    type=int,
    help="Backend port to stop. Defaults to global --port from config.",
)
@click.pass_context
def shutdown_cmd(ctx: click.Context, port: Optional[int]) -> None:
    """Stop the running QwenPaw app processes.

    `qwenpaw app` only starts the backend process. The web console is normally
    static files served by that backend. During frontend development, a
    separate Vite process may also be running from the repository's
    `console/` directory, and this command will stop that as well.
    """
    backend_port = _backend_port(ctx, port)
    backend_pids = _listening_pids_for_port(backend_port)
    frontend_pids = _find_frontend_dev_pids()
    desktop_pids = _find_desktop_wrapper_pids()
    wrapper_pids = _find_windows_wrapper_ancestor_pids(backend_pids)

    # Build a process table for logging.
    proc_table = dict(_process_table())

    def log_pid_set(title, pids):
        if not pids:
            click.echo(f"{title}: nothing to stop")
            return
        click.echo(f"{title} ({len(pids)} total):")
        for pid in sorted(pids):
            cmd = proc_table.get(pid, "<unknown command line>")
            click.echo(f"  PID {pid}: {cmd}")

    log_pid_set("Backend listener processes", backend_pids)
    log_pid_set("Frontend development processes", frontend_pids)
    log_pid_set("Desktop wrapper processes", desktop_pids)
    log_pid_set("Related wrapper processes", wrapper_pids)

    all_targets = backend_pids | frontend_pids | desktop_pids | wrapper_pids
    if not all_targets:
        raise click.ClickException(
            "No running QwenPaw backend/frontend process was found.",
        )

    wrapper_stopped, wrapper_failed = _stop_pid_set(wrapper_pids)
    frontend_stopped, frontend_failed = _stop_pid_set(frontend_pids)
    desktop_stopped, desktop_failed = _stop_pid_set(
        desktop_pids - set(wrapper_stopped) - set(frontend_stopped),
    )
    backend_stopped, backend_failed = _stop_pid_set(
        backend_pids
        - set(wrapper_stopped)
        - set(frontend_stopped)
        - set(desktop_stopped),
    )

    stopped = (
        wrapper_stopped + frontend_stopped + desktop_stopped + backend_stopped
    )
    failed = list(
        set(
            wrapper_failed + frontend_failed + desktop_failed + backend_failed,
        ),
    )

    if stopped:
        click.echo(
            "Stopped QwenPaw processes: "
            + ", ".join(str(pid) for pid in sorted(stopped)),
        )
    if failed:
        click.echo("Failed to stop the following processes:")
        for pid in sorted(failed):
            cmd = proc_table.get(pid, "<unknown command line>")
            click.echo(f"  PID {pid}: {cmd}")
        raise click.ClickException(
            "Failed to shutdown process(es): "
            + ", ".join(str(pid) for pid in sorted(failed)),
        )
