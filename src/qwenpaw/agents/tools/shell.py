# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""The shell command tool."""

import asyncio
import locale
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, BinaryIO, Optional

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from ...config.context import (
    get_current_project_dir,
    get_current_shell_command_executable,
    get_current_shell_command_timeout,
    get_current_workspace_dir,
)
from ...constant import WORKING_DIR
from ...runtime.tool_registry import tool_descriptor
from ...sandbox import ExecutionResult
from ...sandbox.config import SandboxConfig
from ...utils.io_utils import run_sync_io

_SHELL_OUTPUT_MAX_BYTES = 1024 * 1024
_SHELL_OUTPUT_DRAIN_GRACE_SECS = 10.0


def _kill_process_tree_win32(pid: int) -> None:
    """Kill a process and all its descendants on Windows via taskkill.

    Uses ``taskkill /F /T`` which forcefully terminates the entire process
    tree, including grandchild processes that ``Popen.kill()`` would miss.
    """
    try:
        subprocess.call(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except Exception:
        pass


def _windows_shell_creationflags() -> int:
    """Return Windows process flags for shell commands."""
    return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def _collapse_embedded_newlines(
    cmd: str,
    shell_executable: str | None = None,
) -> str:
    r"""Normalize embedded newlines for the configured shell.

    Unix-like shells natively assign meaning to newlines in command lists,
    control structures, comments, and heredocs.  Rewriting those newlines
    changes the program, so commands on Unix/macOS are passed through
    unchanged.

    On Windows, PowerShell also supports multiline scripts and keeps the
    original command.  ``cmd.exe`` (and unknown cmd-like shells) can truncate
    at embedded line breaks, so that path retains the existing CRLF/LF
    normalization behavior.
    """
    if "\n" not in cmd:
        return cmd
    if sys.platform != "win32":
        return cmd
    if shell_executable and _is_powershell(shell_executable):
        return cmd
    return cmd.replace("\r\n", " ").replace("\n", " ")


def _sanitize_win_cmd(cmd: str) -> str:
    """Fix common LLM escaping artefacts for Windows ``cmd.exe``.

    LLMs sometimes produce commands with backslash-escaped double quotes
    (``\\"``) — valid in bash/JSON but meaningless to ``cmd.exe``.  When
    *every* double-quote in the command is preceded by a backslash, it is
    almost certainly a double-escape artefact, so we strip them.
    """
    if '\\"' in cmd and '"' not in cmd.replace('\\"', ""):
        return cmd.replace('\\"', '"')
    return cmd


def _read_output_snapshot(
    output_file: BinaryIO,
    max_bytes: int = _SHELL_OUTPUT_MAX_BYTES,
) -> str:
    """Read one fixed, bounded snapshot from a temporary output file."""
    try:
        snapshot_size = os.fstat(output_file.fileno()).st_size
        capture_limit = max(0, max_bytes)
        capture_size = min(snapshot_size, capture_limit)
        output_file.seek(0)
        data = output_file.read(capture_size)
    except OSError:
        return ""

    text = smart_decode(data)
    if snapshot_size > len(data):
        notice = (
            f"⚠️ Output truncated: captured the first {len(data)} bytes "
            f"from a {snapshot_size}-byte snapshot "
            f"(limit: {capture_limit} bytes)."
        )
        return f"{text}\n{notice}" if text else notice
    return text


def _read_temp_file(
    path: str,
    max_bytes: int = _SHELL_OUTPUT_MAX_BYTES,
) -> str:
    """Read one fixed, bounded snapshot from a temporary output path."""
    try:
        with open(path, "rb") as output_file:
            return _read_output_snapshot(output_file, max_bytes)
    except OSError:
        return ""


def _open_temp_output(prefix: str) -> tuple[BinaryIO, str]:
    """Create a temporary output file without leaking its raw descriptor."""
    fd, path = tempfile.mkstemp(prefix=prefix)
    try:
        return os.fdopen(fd, "wb"), path
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass
        raise


@dataclass
class _PosixTempOutputs:
    """POSIX temporary output resources managed in a worker thread."""

    stdout_file: BinaryIO | None = None
    stderr_file: BinaryIO | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None

    @classmethod
    def create(cls) -> "_PosixTempOutputs":
        outputs = cls()
        try:
            outputs.stdout_file, outputs.stdout_path = _open_temp_output(
                "qwenpaw_out_",
            )
            outputs.stderr_file, outputs.stderr_path = _open_temp_output(
                "qwenpaw_err_",
            )
            return outputs
        except BaseException:
            outputs.cleanup()
            raise

    def close_writers(self) -> None:
        """Close parent writer copies after the shell inherits them."""
        for attr in ("stdout_file", "stderr_file"):
            output_file = getattr(self, attr)
            if output_file is not None:
                try:
                    output_file.close()
                except OSError:
                    pass
                setattr(self, attr, None)

    def read_snapshot(
        self,
        max_bytes: int = _SHELL_OUTPUT_MAX_BYTES,
    ) -> tuple[str, str]:
        """Read bounded stdout and stderr snapshots."""
        stdout = (
            _read_temp_file(self.stdout_path, max_bytes)
            if self.stdout_path is not None
            else ""
        )
        stderr = (
            _read_temp_file(self.stderr_path, max_bytes)
            if self.stderr_path is not None
            else ""
        )
        return stdout, stderr

    def cleanup(self) -> None:
        """Close writers and unlink both temporary paths."""
        self.close_writers()
        for attr in ("stdout_path", "stderr_path"):
            path = getattr(self, attr)
            if path is not None:
                try:
                    os.unlink(path)
                except OSError:
                    pass
                setattr(self, attr, None)


def _open_windows_temp_output(prefix: str) -> tuple[Any, BinaryIO]:
    """Create Windows output handles that delete after the last close.

    The writer is inherited by the shell and possibly its background
    descendants.  Opening both handles with ``O_TEMPORARY`` gives them delete
    sharing and marks the file for automatic deletion when the final inherited
    handle closes.  The separate reader has its own file position, so reading
    captured output cannot disturb a descendant that still holds the writer.
    """
    # The handle must outlive this helper and be inherited by the child.
    # pylint: disable-next=consider-using-with
    writer = tempfile.NamedTemporaryFile(
        mode="w+b",
        prefix=prefix,
        delete=True,
    )
    reader_fd: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_TEMPORARY", 0)
        reader_fd = os.open(writer.name, flags)
        reader = os.fdopen(reader_fd, "rb")
        reader_fd = None
        return writer, reader
    except BaseException:
        if reader_fd is not None:
            try:
                os.close(reader_fd)
            except OSError:
                pass
        try:
            writer.close()
        except OSError:
            pass
        raise


def _read_temp_output(
    output_file: BinaryIO,
    max_bytes: int = _SHELL_OUTPUT_MAX_BYTES,
) -> str:
    """Read a bounded snapshot from an independent Windows handle."""
    return _read_output_snapshot(output_file, max_bytes)


def _consume_background_task(task: asyncio.Task[Any]) -> None:
    """Consume a detached task result so late I/O errors are not reported."""
    try:
        task.result()
    except BaseException:
        pass


async def _drain_output_snapshot(
    snapshot_task: asyncio.Task[tuple[str, str]],
) -> tuple[str, str]:
    """Wait briefly for bounded snapshot I/O after timeout or cancellation."""
    try:
        return await asyncio.wait_for(
            asyncio.shield(snapshot_task),
            timeout=_SHELL_OUTPUT_DRAIN_GRACE_SECS,
        )
    except asyncio.TimeoutError:
        snapshot_task.add_done_callback(_consume_background_task)
        notice = (
            "⚠️ Output collection omitted: snapshot I/O did not finish "
            f"within {_SHELL_OUTPUT_DRAIN_GRACE_SECS:g} seconds."
        )
        return "", notice
    except asyncio.CancelledError:
        snapshot_task.add_done_callback(_consume_background_task)
        raise


def _shell_basename(executable: str) -> str:
    """Extract lowercase basename from a path using both / and \\ separators."""
    return executable.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _is_powershell(executable: str) -> bool:
    """Check if the given executable path is a PowerShell variant."""
    return _shell_basename(executable) in (
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
    )


def _is_cmd(executable: str) -> bool:
    """Check if the given executable path is cmd.exe."""
    return _shell_basename(executable) in ("cmd", "cmd.exe")


_PS_CMD_RE = re.compile(
    r"^(powershell(?:\.exe)?|pwsh(?:\.exe)?)"
    r"((?:\s+-(?:NoProfile|NonInteractive|NoLogo))*)"
    r"(?:\s+-ExecutionPolicy\s+\S+)?"
    r"\s+-Command\s+",
    re.IGNORECASE,
)


def _extract_powershell_command(cmd: str) -> tuple[str | None, str]:
    """Detect ``powershell -Command <body>`` and return (exe, inner_body).

    When *cmd* starts with a PowerShell invocation followed by ``-Command``,
    extract the executable name and the inner command body (with a single
    layer of surrounding double-quotes removed if present).

    Returns ``(None, cmd)`` unchanged when no PowerShell prefix is found.
    """
    m = _PS_CMD_RE.match(cmd)
    if not m:
        return None, cmd
    ps_exe = m.group(1)
    inner = cmd[m.end() :]
    if len(inner) >= 2 and inner[0] == '"' and inner[-1] == '"':
        inner = inner[1:-1]
    return ps_exe, inner


# pylint: disable=too-many-branches, too-many-statements
def _execute_subprocess_sync(
    cmd: str,
    cwd: str,
    timeout: float | None,
    env: dict | None = None,
    shell_executable: str | None = None,
    stop_event: threading.Event | None = None,
) -> tuple[int, str, str]:
    """Execute subprocess synchronously in a thread.

    This function runs in a separate thread to avoid Windows asyncio
    subprocess limitations.

    stdout/stderr are redirected to temporary files instead of pipes.
    On Windows, child processes inherit pipe handles and keep them open
    even after the parent exits, which causes ``communicate()`` to block
    until *all* holders close (e.g. a Chrome process launched via
    ``Start-Process``).  With temp-file redirection, ``proc.wait()``
    only waits for the direct child (``cmd.exe``) to exit, so commands
    that spawn background processes return immediately.

    When *stop_event* is set (bridged from ``cancel_event`` / kill
    deadline), the process tree is killed via
    :func:`_kill_process_tree_win32` so host cancel is not ignored.

    When *timeout* is ``None``, only *stop_event* or natural process exit
    ends the wait — used under ``ToolCallContext`` so ``extend_kill`` /
    ``no_deadline`` can update lifetime without a frozen sync ceiling.

    .. note::

       Callers must pre-process *cmd* through
       :func:`_collapse_embedded_newlines` before passing it here.
       ``execute_shell_command`` already does this.

    Args:
        cmd (`str`):
            The shell command to execute. PowerShell commands may contain
            embedded newlines; other Windows shell commands are normalized
            by the caller as described above.
        cwd (`str`):
            The working directory for the command execution.
        timeout (`float | None`):
            Hard wall-clock limit, or ``None`` to wait until stop/exit.
        env (`dict | None`):
            Environment variables for the subprocess.
        shell_executable (`str | None`):
            Path to the shell executable. When ``None``, defaults to
            ``cmd.exe``.
        stop_event (`threading.Event | None`):
            Optional cooperative stop signal from the asyncio side.

    Returns:
        `tuple[int, str, str]`:
            A tuple containing the return code, standard output, and
            standard error of the executed command. If timeout occurs, the
            return code will be -1 and stderr will contain timeout information.
    """
    stdout_path: str | None = None
    stderr_path: str | None = None
    stdout_file = None
    stderr_file = None
    stdout_reader = None
    stderr_reader = None

    try:
        if shell_executable and _is_powershell(shell_executable):
            # Strip redundant powershell/pwsh -Command wrapper that the
            # LLM may emit even though the shell is already PowerShell.
            _, cmd = _extract_powershell_command(cmd)
            wrapped = [
                shell_executable,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                cmd,
            ]
        elif not shell_executable or _is_cmd(shell_executable):
            cmd = _sanitize_win_cmd(cmd)
            shell_name = shell_executable or "cmd"
            wrapped = f'{shell_name} /D /S /C "{cmd}"'
        else:
            # POSIX-like shell on Windows (e.g. Git Bash, MSYS2)
            wrapped = [shell_executable, "-c", cmd]

        if sys.platform == "win32":
            stdout_file, stdout_reader = _open_windows_temp_output(
                "qwenpaw_out_",
            )
            stderr_file, stderr_reader = _open_windows_temp_output(
                "qwenpaw_err_",
            )
        else:
            stdout_file, stdout_path = _open_temp_output("qwenpaw_out_")
            stderr_file, stderr_path = _open_temp_output("qwenpaw_err_")

        proc = subprocess.Popen(  # pylint: disable=consider-using-with
            wrapped,
            shell=False,
            stdout=stdout_file,
            stderr=stderr_file,
            text=False,
            cwd=cwd,
            env=env,
            creationflags=_windows_shell_creationflags(),
        )

        # Parent copies are no longer needed — the child inherited its own
        # handles via CreateProcess.  Closing here avoids holding the files
        # open longer than necessary.
        stdout_file.close()
        stdout_file = None
        stderr_file.close()
        stderr_file = None

        timed_out = False
        stopped = False
        deadline = (
            None if timeout is None else time.monotonic() + max(0.0, timeout)
        )
        poll_secs = 0.2
        while True:
            if stop_event is not None and stop_event.is_set():
                stopped = True
                break
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                wait_for = min(poll_secs, remaining)
            else:
                wait_for = poll_secs
            try:
                proc.wait(timeout=wait_for)
                break
            except subprocess.TimeoutExpired:
                continue

        if timed_out or stopped:
            _kill_process_tree_win32(proc.pid)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass

        if stdout_reader is not None and stderr_reader is not None:
            stdout_str = _read_temp_output(
                stdout_reader,
                _SHELL_OUTPUT_MAX_BYTES,
            )
            stderr_str = _read_temp_output(
                stderr_reader,
                _SHELL_OUTPUT_MAX_BYTES,
            )
        else:
            stdout_str = _read_temp_file(
                stdout_path,
                _SHELL_OUTPUT_MAX_BYTES,
            )
            stderr_str = _read_temp_file(
                stderr_path,
                _SHELL_OUTPUT_MAX_BYTES,
            )

        if stopped:
            # Async side replaces with cancel/timeout stderr via cancel_reason.
            return -1, stdout_str, stderr_str
        if timed_out:
            timeout_msg = (
                f"Command execution exceeded the timeout of {timeout} seconds."
            )
            if stderr_str:
                stderr_str = f"{stderr_str}\n{timeout_msg}"
            else:
                stderr_str = timeout_msg
            return -1, stdout_str, stderr_str

        returncode = proc.returncode if proc.returncode is not None else -1
        return returncode, stdout_str, stderr_str

    except Exception as e:
        return -1, "", str(e)
    finally:
        for f in (
            stdout_file,
            stderr_file,
            stdout_reader,
            stderr_reader,
        ):
            if f is not None:
                try:
                    f.close()
                except OSError:
                    pass
        for path in (stdout_path, stderr_path):
            if path is not None:
                try:
                    os.unlink(path)
                except OSError:
                    pass


# Extra seconds added to the tool-call deadline to accommodate first-time
# sandbox creation (user provisioning, profile creation, firewall rules, ACLs).
# Subsequent calls hit the cache and need no extension.
_SANDBOX_SETUP_DEADLINE_EXTENSION = 180.0


def _cancel_stderr_message(timeout: float) -> str:
    """Stderr suffix for CancelledError from cancellable_wait.

    Coordinator kill_deadline expiry sets ``CancelReason.TIMEOUT``; user/API
    cancel sets ``CancelReason.USER``. Distinguish them for LLM-facing text.
    """
    from ...tool_calls import get_call_context
    from ...tool_calls._context import CancelReason

    ctx = get_call_context()
    if ctx is not None and ctx.cancel_reason == CancelReason.TIMEOUT:
        return (
            f"⚠️ TimeoutError: The command execution exceeded "
            f"the timeout of {timeout} seconds. "
            f"Please consider increasing the timeout value if this "
            f"command requires more time to complete."
        )
    if ctx is not None and ctx.cancel_reason == CancelReason.USER:
        return (
            "⚠️ Command execution was cancelled by the user. "
            "Do not retry this command unless the user explicitly asks."
        )
    return "⚠️ Command execution was cancelled."


async def _execute_windows_host(
    cmd: str,
    cwd: str,
    timeout: float,
    env: dict[str, str],
    shell_executable: str | None,
) -> tuple[int, str, str]:
    """Windows host shell with kill_deadline + cancel_event process kill.

    ``asyncio.to_thread`` alone ignores cancel, and wrapping it in
    ``cancellable_wait`` can cancel the awaitable before the worker thread
    observes stop. Instead: arm ``kill_deadline``, bridge ``cancel_event`` to
    a ``threading.Event``, and let the sync helper kill the process tree.

    Under ``ToolCallContext``, the sync helper gets ``timeout=None`` so
    lifetime follows ``kill_deadline`` (extend / ``no_deadline`` / cancel)
    rather than a frozen copy of the original command timeout.
    """
    from ...tool_calls import arm_kill_deadline, get_call_context

    stop_event = threading.Event()
    ctx = get_call_context()
    if ctx is not None:
        arm_kill_deadline(ctx, timeout)

    # Context present: coordinator owns kill via cancel_event → stop_event.
    # No context (SDK/direct): keep a local sync wall-clock timeout.
    sync_timeout: float | None = None if ctx is not None else timeout

    async def _bridge_cancel() -> None:
        if ctx is None:
            return
        await ctx.cancel_event.wait()
        stop_event.set()

    bridge = asyncio.create_task(_bridge_cancel())
    try:
        returncode, stdout_str, stderr_str = await asyncio.to_thread(
            _execute_subprocess_sync,
            cmd,
            cwd,
            sync_timeout,
            env,
            shell_executable,
            stop_event,
        )
        if ctx is not None and ctx.cancel_event.is_set():
            return -1, stdout_str, _cancel_stderr_message(timeout)
        return returncode, stdout_str, stderr_str
    finally:
        # Always arm stop: if the awaiting task is cancelled (force cancel)
        # without cancel_event, the worker thread must still kill the tree.
        stop_event.set()
        if not bridge.done():
            bridge.cancel()
            try:
                await bridge
            except asyncio.CancelledError:
                pass


async def _execute_in_sandbox(
    cmd: str,
    sandbox_config: Any,
    timeout: float,
    cwd: str,
    env: dict[str, str],
) -> ExecutionResult:
    """Execute a shell command inside the sandbox and return raw result.

    On first invocation the sandbox setup (user creation, profile, ACLs,
    firewall rules) can take 5-100+ seconds. During setup we temporarily
    extend existing coordinator deadlines; after setup we restore them by
    shifting absolute deadlines forward by the setup elapsed time so the
    remaining offload/kill budgets are unchanged. Then we register
    ``kill_deadline`` for the command ``timeout`` only around
    ``sandbox.execute`` (never rewrite ``offload_deadline`` to the command
    timeout — that would collapse offload and kill into the same instant).
    """
    from ...sandbox import create_sandbox
    from ...tool_calls import (
        COORDINATOR_OWNED_EXEC_TIMEOUT_SECS,
        cancellable_wait,
        get_call_context,
    )

    # Sandbox backends rebuild their environment from os.environ. Carry over
    # the PATH adjusted by the shell entrypoint unless policy set one itself.
    sandbox_env = dict(sandbox_config.env_vars)
    if not any(key.upper() == "PATH" for key in sandbox_env):
        path_key = next(
            (key for key in env if key.upper() == "PATH"),
            "PATH",
        )
        sandbox_env[path_key] = env[path_key]

    ctx = get_call_context()
    # Under ToolCallContext the coordinator owns kill via cancellable_wait /
    # cancel_event. Do not freeze sandbox wait_for to the original timeout or
    # ``extend_kill_deadline`` cannot actually prolong execution.
    sandbox_timeout = (
        COORDINATOR_OWNED_EXEC_TIMEOUT_SECS
        if ctx is not None
        else int(timeout)
    )
    effective_config = replace(
        sandbox_config,
        timeout_seconds=sandbox_timeout,
        env_vars=sandbox_env,
    )
    loop = asyncio.get_running_loop()
    setup_started_at = loop.time()
    original_offload = None
    original_kill = None
    if ctx is not None:
        if ctx.offload_deadline is not None:
            original_offload = ctx.offload_deadline
            ctx.offload_deadline += _SANDBOX_SETUP_DEADLINE_EXTENSION
        if ctx.kill_deadline is not None:
            original_kill = ctx.kill_deadline
            ctx.kill_deadline += _SANDBOX_SETUP_DEADLINE_EXTENSION
        if original_offload is not None or original_kill is not None:
            ctx.deadline_changed_event.set()

    def _restore_setup_deadlines() -> None:
        """Restore deadlines so remaining time matches pre-setup remaining.

        Writing back the pre-setup absolute timestamp would still charge
        setup duration against the budget; shift forward by elapsed setup.
        """
        if ctx is None:
            return
        elapsed = max(
            0.0,
            asyncio.get_running_loop().time() - setup_started_at,
        )
        changed = False
        if original_offload is not None:
            ctx.offload_deadline = original_offload + elapsed
            changed = True
        if original_kill is not None:
            ctx.kill_deadline = original_kill + elapsed
            changed = True
        if changed:
            ctx.deadline_changed_event.set()

    try:
        async with create_sandbox(effective_config) as sandbox:
            # Setup finished: compensate setup elapsed on borrowed deadlines,
            # then arm kill_deadline for the command timeout only.
            _restore_setup_deadlines()
            return await cancellable_wait(
                sandbox.execute(cmd, cwd=cwd),
                fallback_secs=timeout,
                as_kill_deadline=True,
            )
    except BaseException:
        _restore_setup_deadlines()
        raise


_DANGER_NAMES = {
    "python",
    "pythonw",
    "cmd",
    "powershell",
    "pwsh",
    "conhost",
}

# Prefix: kill/taskkill at command start or after &&, ;, |
_KILL_PREFIX = r"(?:^|[;&|]\s*)\s*"

# Matches PID-based kills: taskkill /PID 123, kill -9 123, kill 123.
_KILL_PID_RE = re.compile(
    rf"{_KILL_PREFIX}(?:taskkill|kill|stop-process)\b"
    rf".*(?:/PID|-p|-pid|\b)\s*(\d+)",
    re.IGNORECASE,
)

# Matches dangerous process names as /IM targets or bare kill targets.
_DANGER_NAME_RE = re.compile(
    rf"{_KILL_PREFIX}(?:taskkill|kill|stop-process)\b"
    rf".*?\b({'|'.join(_DANGER_NAMES)})(?:\.exe)?\b",
    re.IGNORECASE,
)

# Shell variables that reference the current/parent PID.
_SHELL_PID_VARS = {"$$", "$ppid", "$pid"}


def _is_dangerous_self_kill(cmd: str) -> bool:
    """Return True if *cmd* would kill the current process or its parent.

    Uses token-based regex matching to avoid false positives from
    substring matching (e.g. ``echo "do not kill python"`` is safe).

    Blocks three patterns:
    1. ``taskkill /IM <dangerous_name>`` — kills by image name.
    2. ``kill <pid>`` / ``taskkill /PID <pid>`` targeting our PID or
       parent.
    3. Shell variable self-kill: ``kill -9 $$``, ``kill $PPID``.
    """
    lower = cmd.lower()

    if _DANGER_NAME_RE.search(lower):
        return True

    if "kill" in lower or "stop-process" in lower:
        if any(var in lower for var in _SHELL_PID_VARS):
            return True

    m = _KILL_PID_RE.search(lower)
    if m:
        try:
            target_pid = int(m.group(1))
            protected_pids = {os.getpid()}
            if hasattr(os, "getppid"):
                protected_pids.add(os.getppid())
            if target_pid in protected_pids:
                return True
        except ValueError:
            pass

    return False


async def _cleanup_proc(proc: asyncio.subprocess.Process) -> None:
    """Kill a timed-out or cancelled POSIX subprocess group."""
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except asyncio.TimeoutError:
            os.killpg(pgid, signal.SIGKILL)
            await asyncio.wait_for(proc.wait(), timeout=2)
    except (ProcessLookupError, OSError):
        try:
            proc.kill()
            await proc.wait()
        except (ProcessLookupError, OSError):
            pass


async def _execute_posix_host(
    cmd: str,
    cwd: str,
    timeout: float,
    env: dict[str, str],
    shell_executable: str | None,
) -> tuple[int, str, str]:
    """Execute a POSIX host command without pipe-inheritance hangs.

    A background descendant can inherit stdout/stderr pipe descriptors after
    the direct shell exits.  Waiting on ``communicate()`` would then wait for
    every such descendant to close the descriptors.  Redirect output to
    regular temporary files instead, and wait only for the direct shell.
    Once it exits, capture at most ``_SHELL_OUTPUT_MAX_BYTES`` from the fixed
    file-size snapshot observed at that moment.  Background services must
    redirect their own stdout/stderr; inherited descriptors can otherwise keep
    consuming storage even after the temporary path is unlinked.
    """
    outputs: _PosixTempOutputs | None = None
    loop = asyncio.get_running_loop()
    local_deadline = loop.time() + max(0.0, timeout)

    def remaining_timeout() -> float:
        """Return the direct-call budget left for the next async phase."""
        return max(0.0, local_deadline - loop.time())

    try:
        outputs = await run_sync_io(_PosixTempOutputs.create)
        if outputs.stdout_file is None or outputs.stderr_file is None:
            raise RuntimeError("Temporary output files were not created")

        proc = await asyncio.create_subprocess_exec(
            shell_executable or "/bin/sh",
            "-c",
            cmd,
            stdout=outputs.stdout_file,
            stderr=outputs.stderr_file,
            bufsize=0,
            cwd=cwd,
            env=env,
            start_new_session=True,
        )

        # The child inherited its own descriptors.  Close the parent copies
        # before waiting, then reopen the paths for reading after the shell
        # exits.  Background descendants may keep their descriptors open, but
        # regular files do not have pipe EOF semantics and cannot block wait().
        await run_sync_io(outputs.close_writers)

        stderr_suffix = ""
        try:
            from ...tool_calls import cancellable_wait

            returncode = await cancellable_wait(
                proc.wait(),
                fallback_secs=remaining_timeout(),
                as_kill_deadline=True,
            )
        except asyncio.TimeoutError:
            stderr_suffix = (
                f"⚠️ TimeoutError: The command execution exceeded "
                f"the timeout of {timeout} seconds. "
                f"Please consider increasing the timeout value if this "
                f"command requires more time to complete."
            )
            returncode = -1
            await _cleanup_proc(proc)
        except asyncio.CancelledError:
            stderr_suffix = _cancel_stderr_message(timeout)
            returncode = -1
            await _cleanup_proc(proc)

        # Monitor the same cancellation source while collecting output.  The
        # worker itself cannot be interrupted safely, so shield it, wait for
        # the bounded snapshot to finish, then surface cancel/timeout and
        # clean up.  This avoids leaving a reader racing with unlink().
        snapshot_task = asyncio.create_task(
            run_sync_io(
                outputs.read_snapshot,
                _SHELL_OUTPUT_MAX_BYTES,
            ),
        )
        try:
            stdout_str, stderr_str = await cancellable_wait(
                asyncio.shield(snapshot_task),
                fallback_secs=remaining_timeout(),
            )
        except asyncio.TimeoutError:
            stdout_str, stderr_str = await _drain_output_snapshot(
                snapshot_task,
            )
            stderr_suffix = (
                f"⚠️ TimeoutError: The command execution exceeded "
                f"the timeout of {timeout} seconds. "
                f"Please consider increasing the timeout value if this "
                f"command requires more time to complete."
            )
            returncode = -1
        except asyncio.CancelledError:
            stdout_str, stderr_str = await _drain_output_snapshot(
                snapshot_task,
            )
            from ...tool_calls import get_call_context

            ctx = get_call_context()
            if ctx is None or not ctx.cancel_event.is_set():
                raise
            stderr_suffix = _cancel_stderr_message(timeout)
            returncode = -1
        if stderr_suffix:
            if stderr_str:
                stderr_str += f"\n{stderr_suffix}"
            else:
                stderr_str = stderr_suffix
        return returncode, stdout_str, stderr_str
    finally:
        if outputs is not None:
            await run_sync_io(outputs.cleanup)


# TODO: Add dedicated support for long-running processes through a managed
#  session model. Keep processes under framework ownership, return a session ID
#  while they are running, capture stdout and stderr in bounded head-and-tail
#  buffers, allow callers to poll new output and stop sessions explicitly,
#  limit active sessions, and terminate the entire process tree when a
#  session  stops or expires, or when the application shuts down.
# pylint: disable=too-many-branches, too-many-statements
@tool_descriptor(
    requires_sandbox=("shell_exec",),
    async_execution=True,
    tool_type="shell",
    target_param="command",
    policy_name="Bash",
    ui_description="Execute shell commands",
    ui_icon="💻",
)
async def execute_shell_command(
    command: str,
    timeout: float = 60.0,
    cwd: Optional[Path] = None,
    sandbox_config: Optional[Any] = None,
) -> ToolChunk:
    """Execute a shell command and return its output.

    Each call runs in a fresh subprocess — `cd`, `export`, `source`,
    etc. do NOT persist. Pass `cwd=` or chain in one call
    (`cd /repo && pytest`).

    IMPORTANT: Check the 'Default Shell' field to
    determine which shell is active, and generate commands using the
    appropriate syntax (e.g. bash vs PowerShell vs cmd.exe).

    IMPORTANT: Do not use nohup or other commands to start long-running
    background processes. If unavoidable, explicitly redirect stdin,
    stdout, and stderr.

    Args:
        command (`str`):
            The shell command to execute.
        timeout (`float`, defaults to `60.0`):
            The maximum time (in seconds) allowed for the command to run.
            Default is 60.0 seconds.
        cwd (`Optional[Path]`, defaults to `None`):
            The working directory for the command execution.
            If None, defaults to the agent workspace.
        sandbox_config (`Optional[Any]`, defaults to `None`):
            Sandbox execution configuration compiled from governance policy.
            When provided, the command executes within a sandboxed environment
            with the specified mount permissions and network restrictions.

    Returns:
        `ToolChunk`:
            The tool response containing the return code, standard output, and
            standard error of the executed command. If timeout occurs, the
            return code will be -1 and stderr will contain timeout information.
    """

    shell_executable = (
        get_current_shell_command_executable()
        or os.environ.get("SHELL")
        or None
    )
    cmd = _collapse_embedded_newlines(
        (command or "").strip(),
        shell_executable=shell_executable,
    )

    if _is_dangerous_self_kill(cmd):
        return ToolChunk(
            is_last=True,
            state=ToolResultState.ERROR,
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "Blocked: this command would terminate the "
                        "QwenPaw process or its parent. "
                        "Refusing to execute."
                    ),
                ),
            ],
        )

    if isinstance(timeout, str):
        try:
            timeout = float(timeout)
        except (ValueError, TypeError):
            timeout = 60.0

    # Apply agent-configured default when the caller used the hardcoded
    # default (60.0).  An explicit LLM-provided value != 60.0 is kept.
    if timeout == 60.0:
        configured = get_current_shell_command_timeout()
        if configured is not None:
            timeout = configured

    if cwd is not None:
        working_dir = cwd
    else:
        working_dir = (
            get_current_project_dir()
            or get_current_workspace_dir()
            or WORKING_DIR
        )

    # Ensure the venv Python is on PATH for subprocesses
    env = os.environ.copy()
    python_bin_dir = str(Path(sys.executable).parent)
    existing_path = env.get("PATH", "")
    if existing_path:
        env["PATH"] = python_bin_dir + os.pathsep + existing_path
    else:
        env["PATH"] = python_bin_dir

    if sandbox_config is not None and not isinstance(
        sandbox_config,
        SandboxConfig,
    ):
        sandbox_config = None

    if sandbox_config is not None:
        # Create a copy with resolved shell and timeout to avoid mutating
        # the shared config object (it may be reused across tool calls).
        sandbox_config = replace(
            sandbox_config,
            shell_executable=shell_executable,
            timeout_seconds=int(timeout),
        )
        try:
            # kill_deadline is armed inside _execute_in_sandbox after setup,
            # so setup time does not consume the command timeout budget and
            # offload_deadline keeps the coordinator's offload semantics.
            result = await _execute_in_sandbox(
                cmd,
                sandbox_config,
                timeout,
                str(working_dir),
                env,
            )
        except asyncio.CancelledError:
            stderr_msg = _cancel_stderr_message(timeout)
            return ToolChunk(
                is_last=True,
                state=ToolResultState.SUCCESS,
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Command failed with exit code -1.\n"
                            f"[stderr]\n{stderr_msg}"
                        ),
                    ),
                ],
            )
        # Sandbox violation: command tried to access something not permitted
        if result.sandbox_violation:
            return ToolChunk(
                is_last=True,
                state=ToolResultState.DENIED,
                content=[
                    TextBlock(
                        type="text",
                        text=f"Sandbox violation: {result.sandbox_violation}\n"
                        f"Command was blocked by sandbox security policy.",
                    ),
                ],
                metadata={"sandbox_violation": result.sandbox_violation},
            )
        if result.exit_code == 0:
            response_text = (
                result.stdout or "Command executed successfully (no output)."
            )
            if result.stderr:
                response_text += f"\n[stderr]\n{result.stderr}"
        else:
            parts = [f"Command failed with exit code {result.exit_code}."]
            if result.stdout:
                parts.append(f"\n[stdout]\n{result.stdout}")
            if result.stderr:
                parts.append(f"\n[stderr]\n{result.stderr}")
            response_text = "".join(parts)
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    type="text",
                    text=response_text,
                ),
            ],
        )

    import logging as _logging

    _logging.getLogger(__name__).debug(
        "[sandbox] SKIP: sandbox_config is None, executing directly",
    )

    try:
        if sys.platform == "win32":
            (
                returncode,
                stdout_str,
                stderr_str,
            ) = await _execute_windows_host(
                cmd,
                str(working_dir),
                timeout,
                env,
                shell_executable,
            )
        else:
            (
                returncode,
                stdout_str,
                stderr_str,
            ) = await _execute_posix_host(
                cmd,
                str(working_dir),
                timeout,
                env,
                shell_executable,
            )

        if returncode == 0:
            if stdout_str:
                response_text = stdout_str
            else:
                response_text = "Command executed successfully (no output)."
            if stderr_str:
                response_text += f"\n[stderr]\n{stderr_str}"
        else:
            response_parts = [f"Command failed with exit code {returncode}."]
            if stdout_str:
                response_parts.append(f"\n[stdout]\n{stdout_str}")
            if stderr_str:
                response_parts.append(f"\n[stderr]\n{stderr_str}")
            response_text = "".join(response_parts)

        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    type="text",
                    text=response_text,
                ),
            ],
        )

    except Exception as e:
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Shell command execution failed due to \n{e}",
                ),
            ],
        )


def smart_decode(data: bytes) -> str:
    try:
        decoded_str = data.decode("utf-8")
    except UnicodeDecodeError:
        encoding = locale.getpreferredencoding(False) or "utf-8"
        decoded_str = data.decode(encoding, errors="replace")

    return decoded_str.strip("\r\n")
