# -*- coding: utf-8 -*-
"""Cancellation and process cleanup for the shared dependency installer."""

import asyncio
import logging
import os
import signal
import subprocess
import threading
import time
from contextlib import suppress
from contextvars import ContextVar

import psutil

from ..utils.command_runner import windows_hidden_subprocess_kwargs

logger = logging.getLogger(__name__)
_CREATE_SUSPENDED = 0x00000004

# Thread offloads inherit these values; unrelated tasks retain their defaults.
install_cancel: ContextVar[threading.Event | None] = ContextVar(
    "dependency_install_cancel",
    default=None,
)
install_timeout: ContextVar[int] = ContextVar(
    "dependency_install_timeout",
    default=300,
)


def check_cancelled(cancel: threading.Event | None) -> None:
    """Propagate cancellation through blocking installer operations."""
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError


def _stop_process_tree(proc: subprocess.Popen, tree=None) -> None:
    """Stop owned installer children before releasing the install lock."""
    if tree is not None:
        tree.signal(force=True)
        proc.wait()
        while tree.alive():
            time.sleep(0.01)
        return
    try:
        children = psutil.Process(proc.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        children = []
    except (psutil.AccessDenied, OSError) as exc:
        # Enumeration is optional: losing permission to inspect processes
        # must not prevent stopping the Popen handle or our POSIX group.
        logger.warning(
            "Cannot enumerate children of dependency installer %s: %s; "
            "continuing process termination",
            proc.pid,
            exc,
        )
        children = []

    def signal_tree(force: bool) -> None:
        # The installer starts a new POSIX session. Its process group survives
        # the parent exiting, so escalation also reaches remaining helpers.
        if os.name != "nt":
            with suppress(ProcessLookupError):
                os.killpg(
                    proc.pid,
                    signal.SIGKILL if force else signal.SIGTERM,
                )
        for child in reversed(children):
            with suppress(psutil.NoSuchProcess):
                if force:
                    child.kill()
                else:
                    child.terminate()
        if proc.poll() is None:
            if force:
                proc.kill()
            else:
                proc.terminate()

    signal_tree(False)
    # One grace period covers parent and children, not one per child.
    deadline = time.monotonic() + 1
    with suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=1)
    psutil.wait_procs(children, timeout=max(0, deadline - time.monotonic()))
    signal_tree(True)
    # Never release a filesystem lock while an installer can still write.
    # The application's shutdown watchdog remains the last resort if even
    # an OS kill cannot stop a process.
    proc.wait()
    psutil.wait_procs(children)


def run_install_command(
    cmd: list[str],
    *,
    timeout: int,
    plugin_id: str,
    cancel: threading.Event | None = None,
) -> subprocess.CompletedProcess:
    """Stream installer output and stop its process tree on cancel/timeout."""
    check_cancelled(cancel)
    logger.debug("Running install command for '%s': %s", plugin_id, cmd)
    output: list[str] = []
    options = windows_hidden_subprocess_kwargs()
    if os.name == "nt":
        # Bind the Job before the installer can create children or exit.
        options["creationflags"] = (
            options.get("creationflags", 0) | _CREATE_SUSPENDED
        )
    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
        start_new_session=os.name != "nt",
        **options,
    ) as proc:

        def read_output() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                stripped = line.rstrip("\n\r")
                if stripped:
                    output.append(stripped)
                    logger.debug("[%s] %s", plugin_id, stripped)

        tree, reader, failure = None, None, None
        try:
            if os.name == "nt":
                from .execution.process_tree import ProcessTree

                tree = ProcessTree(proc.pid)
                check_cancelled(cancel)
                psutil.Process(proc.pid).resume()
            thread = threading.Thread(target=read_output, daemon=True)
            thread.start()
            reader = thread
            deadline = time.monotonic() + timeout
            while True:
                check_cancelled(cancel)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(cmd, timeout)
                try:
                    returncode = proc.wait(timeout=min(0.1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            while reader.is_alive():
                check_cancelled(cancel)
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(cmd, timeout)
                reader.join(timeout=0.1)
            check_cancelled(cancel)
        except BaseException as exc:
            failure = exc
            raise
        finally:
            if failure is not None or tree is not None:
                _stop_process_tree(proc, tree)
            # Keep draining while stopping: closing a pipe from another
            # thread can block behind readline's lock. Exit delivers EOF.
            if reader is not None:
                reader.join()
            if tree is not None:
                tree.close()
            if isinstance(failure, subprocess.TimeoutExpired):
                failure.output = "\n".join(output)

    return subprocess.CompletedProcess(cmd, returncode, "\n".join(output), "")
