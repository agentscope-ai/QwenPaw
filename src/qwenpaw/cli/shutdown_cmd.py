# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from enum import Enum
from pathlib import Path
from typing import Optional

import click
import psutil

from ..process_ownership import observe_backend
from ..shutdown import SERVER_SHUTDOWN_SECONDS
from .process_utils import (
    _is_qwenpaw_wrapper_process,
    _process_table,
    _windows_process_snapshot,
)
from ..utils.windows_shutdown import signal_shutdown_event

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CONSOLE_DIR = (_PROJECT_ROOT / "console").resolve()
_SIGTERM = signal.SIGTERM
_SIGKILL = getattr(signal, "SIGKILL", _SIGTERM)


class ShutdownOutcome(Enum):
    CLOSED = 0
    FAILED = 1
    UNVERIFIED = 3

    def __bool__(self) -> bool:
        return self is ShutdownOutcome.CLOSED


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
    """Signal the target and its descendants."""
    descendants = sorted(_child_pids_unix(pid), reverse=True)
    for target in [*descendants, pid]:
        try:
            os.kill(target, sig)
        except OSError:
            continue


def _terminate_backend_unix(
    pid: int,
    timeout_sec: float,
    process: subprocess.Popen[str] | None,
) -> ShutdownOutcome:
    """Keep identified descendants in custody even after reparenting."""
    try:
        root = psutil.Process(pid)
        if process is not None and process.poll() is not None:
            return ShutdownOutcome.UNVERIFIED
        with observe_backend(root) as ownership:
            return _stop_observed_backend(
                root,
                process,
                timeout_sec,
                ownership,
            )
    except psutil.NoSuchProcess:
        return ShutdownOutcome.UNVERIFIED
    except (OSError, psutil.Error):
        return ShutdownOutcome.FAILED


def _stop_observed_backend(
    root,
    process,
    timeout_sec,
    ownership,
    *,
    supervisor=None,
):
    evidence_readable = True

    def descendants(parent):
        nonlocal evidence_readable
        try:
            if parent.is_running():
                return parent.children(recursive=True)
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            evidence_readable = False
        return []

    def wait_until(deadline, *, force=False):
        nonlocal evidence_readable
        signalled = set()
        while True:
            # Reparented workers can still spawn their own descendants.
            discovered = set()
            for member in pending:
                if member not in discovered:
                    discovered.update(descendants(member))
            pending.update(discovered)
            known.update(pending)
            for member in tuple(pending):
                if process is not None and member == root:
                    # A direct child stays pending until Popen reaps it.
                    if process.poll() is not None:
                        pending.remove(member)
                    continue
                try:
                    if member.is_running() and member.status() not in (
                        psutil.STATUS_ZOMBIE,
                        psutil.STATUS_DEAD,
                    ):
                        continue
                except psutil.NoSuchProcess:
                    pass
                except psutil.AccessDenied:
                    continue
                pending.remove(member)
            if ownership is not None and (not pending or force):
                try:
                    members, resolved = ownership.members(known)
                    pending.update(members)
                except (OSError, psutil.Error, ValueError):
                    # Signal all known handles even if evidence is unreadable.
                    evidence_readable = False
                    resolved = False
                if not pending and resolved:
                    return True
            elif not pending:
                return True
            if force:
                for member in pending - signalled:
                    try:
                        member.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                    signalled.add(member)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(remaining, 0.1))

    deadline = time.monotonic() + timeout_sec
    target = supervisor if supervisor is not None else root
    pending = {target, root, *descendants(target)}
    known = set()
    try:
        target.terminate()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    drained = wait_until(deadline) or wait_until(
        time.monotonic() + 2.0,
        force=True,
    )
    # Empty recorded sessions cannot account for a detached, unseen child.
    if pending or (ownership is not None and ownership.failed):
        return ShutdownOutcome.FAILED
    if drained and evidence_readable and ownership and ownership.closed:
        return ShutdownOutcome.CLOSED
    return ShutdownOutcome.UNVERIFIED


def _signal_process_windows(pid: int) -> bool:
    """Request graceful shutdown from a Windows process group."""
    if signal_shutdown_event(pid):
        return True
    ctrl_break = getattr(signal, "CTRL_BREAK_EVENT", None)
    if ctrl_break is None:
        return False
    try:
        os.kill(pid, ctrl_break)
    except (OSError, ValueError):
        return False
    return True


def _terminate_process_tree_windows(
    pid: int,
    force: bool = False,
    timeout_sec: float = 10.0,
) -> None:
    """Terminate a Windows process tree."""
    command = ["taskkill", "/T", "/PID", str(pid)]
    if force:
        command.insert(1, "/F")
    try:
        subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(0.1, timeout_sec),
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


def _terminate_pid(
    pid: int,
    timeout_sec: float = SERVER_SHUTDOWN_SECONDS,
    process: subprocess.Popen[str] | None = None,
    *,
    backend: bool = False,
) -> ShutdownOutcome:
    """Terminate a process tree gracefully, then force kill if needed.

    When the process is our child, wait on Popen to reap its exit status.
    A departed, unreaped child still appears to exist to os.kill(pid, 0).
    """
    if backend and sys.platform != "win32":
        return _terminate_backend_unix(pid, timeout_sec, process)

    def has_exited() -> bool:
        if process is not None:
            return process.poll() is not None
        return not _pid_exists(pid)

    def wait_for_exit(timeout: float, interval: float) -> bool:
        if process is not None:
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                return False
            return True
        return _wait_for_pid_exit(pid, timeout, interval)

    if has_exited():
        return ShutdownOutcome.CLOSED

    deadline = time.monotonic() + timeout_sec
    if sys.platform == "win32":
        if not _signal_process_windows(pid):
            _terminate_process_tree_windows(
                pid,
                timeout_sec=max(0.0, deadline - time.monotonic()),
            )
    else:
        _signal_process_tree_unix(pid, _SIGTERM)

    if wait_for_exit(max(0.0, deadline - time.monotonic()), 0.2):
        return ShutdownOutcome.CLOSED

    if sys.platform == "win32":
        _terminate_process_tree_windows(pid, force=True, timeout_sec=2.0)
        if wait_for_exit(2.0, 0.1):
            return ShutdownOutcome.CLOSED
        _force_terminate_windows_process(pid)
    else:
        _signal_process_tree_unix(pid, _SIGKILL)

    if wait_for_exit(2.0, 0.1):
        return ShutdownOutcome.CLOSED
    return ShutdownOutcome.FAILED


def _stop_pid_set(
    pids: set[int],
    *,
    backend: bool = False,
) -> dict[int, ShutdownOutcome]:
    """Stop each PID once and preserve its result for the caller."""
    return {pid: _terminate_pid(pid, backend=backend) for pid in sorted(pids)}


def _stop_backend_listeners(
    pids: set[int],
    port: int,
) -> dict[int, ShutdownOutcome]:
    """Verify reload services against their own journal during parent exit."""
    if sys.platform == "win32" or len(pids) < 2:
        return _stop_pid_set(pids, backend=True)

    remaining = pids.copy()
    reload_results = {}
    for pid in sorted(pids):
        if pid not in remaining:
            continue
        try:
            service = psutil.Process(pid)
            supervisor = service.parent()
            if (
                supervisor is None
                or supervisor.pid not in remaining
                or "--reload" not in supervisor.cmdline()
                or service.environ().get("QWENPAW_RELOAD_MODE") != "1"
            ):
                continue
        except psutil.Error:
            continue

        remaining.difference_update((pid, supervisor.pid))
        try:
            with observe_backend(service) as ownership:
                # Uvicorn forwards TERM to its serving child, then joins it.
                outcome = _stop_observed_backend(
                    service,
                    None,
                    SERVER_SHUTDOWN_SECONDS,
                    ownership,
                    supervisor=supervisor,
                )
        except psutil.NoSuchProcess:
            outcome = ShutdownOutcome.UNVERIFIED
        except (OSError, psutil.Error):
            outcome = ShutdownOutcome.FAILED
        reload_results.update(dict.fromkeys((pid, supervisor.pid), outcome))

    others = _stop_pid_set(remaining, backend=True)
    if reload_results and _listening_pids_for_port(port):
        reload_results = dict.fromkeys(reload_results, ShutdownOutcome.FAILED)
    return {**reload_results, **others}


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

    results = _stop_backend_listeners(backend_pids, backend_port)
    for pids in (wrapper_pids, frontend_pids, desktop_pids):
        results.update(_stop_pid_set(pids.difference(results)))

    for outcome, label in (
        (ShutdownOutcome.CLOSED, "Stopped QwenPaw processes"),
        (ShutdownOutcome.UNVERIFIED, "Unable to verify shutdown"),
        (ShutdownOutcome.FAILED, "Shutdown failed"),
    ):
        group = sorted(
            pid for pid, result in results.items() if result is outcome
        )
        if group:
            click.echo(f"{label}: " + ", ".join(map(str, group)))

    if ShutdownOutcome.FAILED in results.values():
        ctx.exit(ShutdownOutcome.FAILED.value)
    if ShutdownOutcome.UNVERIFIED in results.values():
        ctx.exit(ShutdownOutcome.UNVERIFIED.value)
