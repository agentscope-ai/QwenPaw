# -*- coding: utf-8 -*-
"""Background process management tool for long-running commands.

This module provides tools to start, stop, and manage background processes
like HTTP servers, without blocking the main agent execution loop.
"""

import atexit
import asyncio
import logging
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from agentscope.tool import ToolResponse
from agentscope.message import TextBlock

logger = logging.getLogger(__name__)


class ProcessStatus(str, Enum):
    """Status of a background process."""

    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass
class BackgroundProcess:
    """Represents a managed background process."""

    process_id: str
    command: str
    process: subprocess.Popen
    cwd: str
    started_at: datetime
    status: ProcessStatus = ProcessStatus.RUNNING
    pid: Optional[int] = None
    stdout_file: Optional[str] = None
    stderr_file: Optional[str] = None

    def __post_init__(self):
        self.pid = self.process.pid


class BackgroundProcessManager:
    """Singleton manager for background processes.

    This manager tracks all background processes started by the agent,
    allowing them to be monitored and stopped on demand.
    """

    _instance: Optional["BackgroundProcessManager"] = None
    _processes: Dict[str, BackgroundProcess] = {}
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "BackgroundProcessManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._processes = {}
            cls._instance._lock = threading.Lock()
        return cls._instance

    def _check_duplicate(self, process_id: str) -> bool:
        """Check if process_id already exists and is running."""
        with self._lock:
            existing = self._processes.get(process_id)
            if existing and existing.status == ProcessStatus.RUNNING:
                return True
            return False

    def start(
        self,
        command: str,
        cwd: str,
        process_id: Optional[str] = None,
    ) -> BackgroundProcess:
        """Start a new background process.

        Args:
            command: Shell command to execute. Note: This uses shlex.split()
                which means shell features like pipes (|), redirections (>),
                and command chaining (&&, ||) are NOT supported. Only
                simple commands with arguments work.
            cwd: Working directory for the command
            process_id: Optional custom ID (auto-generated if None)

        Returns:
            BackgroundProcess instance tracking the new process

        Raises:
            ValueError: If process_id is already in use by a running process
        """
        process_id = process_id or f"bg_{uuid.uuid4().hex[:8]}"

        # Auto-cleanup stopped processes to prevent file accumulation
        # This runs silently without affecting the new process startup
        self.cleanup_stopped()

        # Check for duplicate process_id
        if self._check_duplicate(process_id):
            raise ValueError(
                f"Process ID '{process_id}' is already in use by a running "
                "process. Use a different ID or stop the existing process "
                "first.",
            )

        # Parse command safely using shlex to avoid shell injection
        # pylint: disable=consider-using-with
        # We intentionally don't use 'with' here because we want the
        # process to continue running in the background
        try:
            # On Windows, use posix=False so backslashes in paths are
            # not treated as escape characters
            is_windows = sys.platform == "win32"
            cmd_args = shlex.split(command, posix=not is_windows)
        except ValueError as e:
            raise ValueError(f"Invalid command format: {e}") from e

        if not cmd_args:
            raise ValueError("Empty command provided")

        # Create temp files for stdout/stderr capture
        # This allows get_process_output() to retrieve output after process
        # stops
        stdout_fd, stdout_path = tempfile.mkstemp(
            prefix=f"copaw_{process_id}_stdout_",
            suffix=".log",
        )
        stderr_fd, stderr_path = tempfile.mkstemp(
            prefix=f"copaw_{process_id}_stderr_",
            suffix=".log",
        )

        # Create process with OS-specific process group isolation
        popen_kwargs: Dict[str, Any] = {
            "shell": False,
            "stdout": stdout_fd,
            "stderr": stderr_fd,
            "cwd": cwd,
        }
        if os.name == "posix":
            # POSIX: use start_new_session for process group isolation
            popen_kwargs["start_new_session"] = True
        elif os.name == "nt":
            # Windows: use creationflags instead
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            process = subprocess.Popen(cmd_args, **popen_kwargs)
        except Exception:
            # Clean up temp files if process fails to start
            os.close(stdout_fd)
            os.close(stderr_fd)
            os.unlink(stdout_path)
            os.unlink(stderr_path)
            raise

        # Close file descriptors in parent process
        os.close(stdout_fd)
        os.close(stderr_fd)

        bg_process = BackgroundProcess(
            process_id=process_id,
            command=command,
            process=process,
            cwd=cwd,
            started_at=datetime.now(),
            stdout_file=stdout_path,
            stderr_file=stderr_path,
        )

        with self._lock:
            self._processes[process_id] = bg_process

        # Log only process_id and PID, not the full command for security
        logger.info(
            "Started background process %s (PID: %s)",
            process_id,
            process.pid,
        )

        return bg_process

    # pylint: disable=too-many-branches
    def stop(self, process_id: str, timeout: int = 5) -> bool:
        """Stop a background process.

        Args:
            process_id: ID of the process to stop
            timeout: Seconds to wait for graceful termination

        Returns:
            True if process was stopped, False if not found, already
            stopped, or failed to stop
        """
        with self._lock:
            bg_process = self._processes.get(process_id)
        if bg_process is None:
            return False

        if bg_process.status != ProcessStatus.RUNNING:
            return False

        # Refresh process status from the underlying Popen instance
        # to avoid acting on a potentially stale PID
        if bg_process.process.poll() is not None:
            # Process has already exited - treat as successfully stopped
            with self._lock:
                bg_process.status = ProcessStatus.STOPPED
            return True

        try:
            if sys.platform == "win32":
                # On Windows, try graceful terminate first
                bg_process.process.terminate()
                try:
                    bg_process.process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # Force kill if graceful termination fails
                    subprocess.run(
                        [
                            "taskkill",
                            "/F",
                            "/T",
                            "/PID",
                            str(bg_process.pid),
                        ],
                        capture_output=True,
                        timeout=timeout,
                        check=False,
                    )
                    # Verify process actually terminated
                    try:
                        bg_process.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        logger.error(
                            "Process %s did not terminate after taskkill",
                            process_id,
                        )
                        # Process still running, return failure
                        return False
            else:
                # On Unix, kill the process group with SIGTERM
                # pid is guaranteed to be set after Popen creation
                assert bg_process.pid is not None
                os.killpg(os.getpgid(bg_process.pid), signal.SIGTERM)

                # Wait for process to terminate
                try:
                    bg_process.process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # Force kill if graceful termination fails
                    os.killpg(
                        os.getpgid(bg_process.pid),
                        signal.SIGKILL,
                    )
                    bg_process.process.kill()
                    bg_process.process.wait(timeout=5)

            with self._lock:
                bg_process.status = ProcessStatus.STOPPED

            # Note: Temp files are NOT deleted here so users can still
            # retrieve output via get_process_output() after stopping.
            # Files will be cleaned up by cleanup_stopped() later.
            logger.info("Stopped background process %s", process_id)
            return True

        except (ProcessLookupError, PermissionError) as e:
            logger.warning("Failed to stop process %s: %s", process_id, e)
            with self._lock:
                bg_process.status = ProcessStatus.STOPPED
            return True

    def get(self, process_id: str) -> Optional[BackgroundProcess]:
        """Get a background process by ID."""
        with self._lock:
            return self._processes.get(process_id)

    def list_all(self) -> Dict[str, BackgroundProcess]:
        """List all tracked background processes."""
        with self._lock:
            return self._processes.copy()

    def list_running(self) -> Dict[str, BackgroundProcess]:
        """List only running processes."""
        with self._lock:
            return {
                process_id: p
                for process_id, p in self._processes.items()
                if p.status == ProcessStatus.RUNNING
            }

    def update_status(self, process_id: str) -> ProcessStatus:
        """Update and return the status of a process."""
        with self._lock:
            bg_process = self._processes.get(process_id)
        if bg_process is None:
            return ProcessStatus.STOPPED

        # Check if process is still running
        returncode = bg_process.process.poll()
        if returncode is not None:
            # Process has terminated
            with self._lock:
                if returncode == 0:
                    bg_process.status = ProcessStatus.STOPPED
                else:
                    bg_process.status = ProcessStatus.FAILED

        return bg_process.status

    def cleanup_stopped(self) -> int:
        """Remove all stopped/failed processes from tracking.

        Returns:
            Number of processes removed
        """
        with self._lock:
            to_remove = [
                process_id
                for process_id, p in self._processes.items()
                if p.status in (ProcessStatus.STOPPED, ProcessStatus.FAILED)
            ]
            for process_id in to_remove:
                # Clean up temp files
                proc = self._processes[process_id]
                if proc.stdout_file and os.path.exists(proc.stdout_file):
                    os.unlink(proc.stdout_file)
                if proc.stderr_file and os.path.exists(proc.stderr_file):
                    os.unlink(proc.stderr_file)
                del self._processes[process_id]
            return len(to_remove)

    def cleanup_all(self) -> None:
        """Stop all running processes.

        This is called on application exit to prevent orphaned processes.
        Note: This method does not clear process tracking; entries remain
        in the internal registry with their final status.
        """
        running = self.list_running()
        for process_id in list(running.keys()):
            try:
                logger.info(
                    "Cleaning up background process %s on exit",
                    process_id,
                )
                self.stop(process_id, timeout=2)
            except Exception as e:
                logger.warning(
                    "Failed to cleanup process %s: %s",
                    process_id,
                    e,
                )


# Global manager instance
_manager: Optional[BackgroundProcessManager] = None


def get_process_manager() -> BackgroundProcessManager:
    """Get the global process manager instance."""
    global _manager
    if _manager is None:
        _manager = BackgroundProcessManager()
        # Register cleanup on exit to prevent orphaned processes
        atexit.register(_manager.cleanup_all)
    return _manager


async def start_background_process(
    command: str,
    process_id: Optional[str] = None,
    cwd: Optional[Path] = None,
) -> ToolResponse:
    """Start a long-running command in the background and return immediately.

    Use this tool for commands that run continuously until manually stopped:

    **Common use cases:**
    - HTTP servers: `python -m http.server 8000`
    - Development servers: `npm run dev`, `flask run`, `django runserver`
    - File watchers: `webpack --watch`, `nodemon`, `tsc --watch`
    - Database servers: `mongod`, `redis-server`, `postgres`
    - Any daemon or service that runs until killed

    Do NOT use for quick commands - use execute_shell_command instead:
    - File operations (ls, cp, mv, rm)
    - Git commands (git status, git log)
    - Package management (pip install, npm install)
    - Any command that finishes by itself

    **Important Limitations:**
    - Shell features like pipes (|), redirections (>), and command
      chaining (&&, ||) are NOT supported
    - Only simple commands with arguments work
    - Environment variable expansion is not supported
    - For complex shell commands, create a script file first

    **About output capture:**
    - Output is captured to temporary files
    - Use get_process_output() to retrieve output after process stops
    - Real-time output is not available

    Args:
        command: The command to execute (program + arguments only,
                 no shell features)
        process_id: Optional custom ID for the process
                    (auto-generated if None)
        cwd: Working directory (defaults to WORKING_DIR)

    Returns:
        ToolResponse with process ID and status information.
        Save the process_id to stop the process later.
    """
    from copaw.constant import WORKING_DIR

    cmd = (command or "").strip()
    if not cmd:
        return ToolResponse(
            content=[
                TextBlock(type="text", text="Error: No command provided"),
            ],
        )

    working_dir = str(cwd) if cwd is not None else str(WORKING_DIR)
    manager = get_process_manager()

    try:
        # Use thread pool to avoid blocking on Windows
        bg_process = await asyncio.to_thread(
            manager.start,
            cmd,
            working_dir,
            process_id,
        )

        started_str = bg_process.started_at.strftime("%Y-%m-%d %H:%M:%S")
        response = (
            f"✅ Background process started successfully!\n\n"
            f"- **Process ID**: `{bg_process.process_id}`\n"
            f"- **PID**: {bg_process.pid}\n"
            f"- **Command**: `{cmd}`\n"
            f"- **Working Dir**: `{working_dir}`\n"
            f"- **Started**: {started_str}\n"
            "\n"
            f"⚠️ **Limitation**: Shell features (pipes, redirections) "
            "are NOT supported.\n\n"
            f"💡 Use `stop_background_process(process_id="
            f'"{bg_process.process_id}")` to stop this process later.\n'
            f"💡 Use `list_background_processes()` to see all running "
            "processes.\n"
            f"💡 Use `get_process_output()` to retrieve output after "
            "stopping."
        )

        return ToolResponse(
            content=[TextBlock(type="text", text=response)],
        )

    except ValueError as e:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: {e}",
                ),
            ],
        )
    except Exception as e:
        logger.exception("Failed to start background process")
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Failed to start background process\n{e}",
                ),
            ],
        )


async def stop_background_process(
    process_id: str,
    timeout: int = 5,
) -> ToolResponse:
    """Stop a running background process by its process_id.

    Use this to stop processes started with start_background_process.

    **Usage:**
    1. First use list_background_processes() to find the process_id
    2. Call stop_background_process(process_id="xxx") to stop it

    Args:
        process_id: ID of the background process to stop (e.g.,
                    "bg_a1b2c3d4")
        timeout: Seconds to wait for graceful termination (default: 5)

    Returns:
        ToolResponse with stop status
    """
    manager = get_process_manager()

    # Refresh status first to avoid stale state
    manager.update_status(process_id)

    bg_process = manager.get(process_id)
    if bg_process is None:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Process `{process_id}` not found. "
                    "Use `list_background_processes()` to see running "
                    "processes.",
                ),
            ],
        )

    if bg_process.status != ProcessStatus.RUNNING:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Process `{process_id}` is not running "
                    f"(status: {bg_process.status})",
                ),
            ],
        )

    try:
        success = await asyncio.to_thread(manager.stop, process_id, timeout)

        if success:
            response = (
                f"✅ Background process stopped successfully!\n\n"
                f"- **Process ID**: `{process_id}`\n"
                f"- **Final Status**: {bg_process.status}\n\n"
                f"💡 Use `get_process_output(process_id="
                f'"{process_id}")` to view captured output.'
            )
        else:
            response = f"⚠️ Failed to stop process `{process_id}`"

        return ToolResponse(
            content=[TextBlock(type="text", text=response)],
        )

    except Exception as e:
        logger.exception("Failed to stop background process")
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error stopping process: {e}",
                ),
            ],
        )


async def list_background_processes(
    include_stopped: bool = False,
) -> ToolResponse:
    """List all background processes started by start_background_process.

    Use this to:
    - See what servers/services are currently running
    - Find the process_id needed to stop a process
    - Check if a previously started process is still alive

    Args:
        include_stopped: Whether to include stopped/failed processes

    Returns:
        ToolResponse with process list showing:
        - process_id (used for stop_background_process)
        - PID (system process ID)
        - Status (running/stopped/failed)
        - Command
        - Running duration
    """
    manager = get_process_manager()

    # Update status of all processes
    for process_id in list(manager.list_all().keys()):
        manager.update_status(process_id)

    if include_stopped:
        processes = manager.list_all()
    else:
        processes = manager.list_running()

    if not processes:
        tip = (
            "\n(Tip: set include_stopped=True to see all)"
            if not include_stopped
            else ""
        )
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"No background processes running.{tip}",
                ),
            ],
        )

    lines = ["## Background Processes\n"]
    for process_id, proc in processes.items():
        status_emoji = "🟢" if proc.status == ProcessStatus.RUNNING else "🔴"
        running_time = (datetime.now() - proc.started_at).total_seconds()

        lines.append(
            f"{status_emoji} **{process_id}**\n"
            f"   - PID: {proc.pid}\n"
            f"   - Status: {proc.status}\n"
            f"   - Command: `{proc.command}`\n"
            f"   - Running for: {running_time:.0f}s\n",
        )

    return ToolResponse(
        content=[TextBlock(type="text", text="\n".join(lines))],
    )


async def get_process_output(
    process_id: str,
) -> ToolResponse:
    """Get the stdout/stderr output from a background process.

    Note: Output is captured to temp files and can be retrieved
    after the process stops. For running processes, the output
    file may be incomplete.

    Args:
        process_id: ID of the background process

    Returns:
        ToolResponse with captured output
    """
    import locale

    manager = get_process_manager()

    bg_process = manager.get(process_id)
    if bg_process is None:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: Process `{process_id}` not found.",
                ),
            ],
        )

    # Update status
    manager.update_status(process_id)

    response_parts = [f"## Output for `{process_id}`\n"]
    response_parts.append(f"- **Status**: {bg_process.status}")
    response_parts.append(f"- **PID**: {bg_process.pid}")
    response_parts.append(f"- **Command**: `{bg_process.command}`\n")

    # Read output from temp files (limit to last 64KB per stream)
    encoding = locale.getpreferredencoding(False) or "utf-8"
    max_bytes = 64 * 1024  # 64 KiB limit per stream

    def _read_tail(path: str) -> tuple[str, bool]:
        """Read at most the last `max_bytes` of the file.
        Returns (content, truncated_flag).
        """
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as f:
                if size > max_bytes:
                    # Seek to start of last `max_bytes` and skip
                    # partial first line deterministically
                    f.seek(size - max_bytes)
                    chunk = f.read()
                    newline_idx = chunk.find(b"\n")
                    if newline_idx != -1:
                        chunk = chunk[newline_idx + 1 :]
                    return chunk.decode(encoding, errors="replace"), True
                data = f.read()
                return data.decode(encoding, errors="replace"), False
        except Exception as e:
            return f"[Error reading file: {e}]", False

    stdout_content = ""
    stderr_content = ""
    stdout_truncated = False
    stderr_truncated = False

    if bg_process.stdout_file and os.path.exists(bg_process.stdout_file):
        stdout_content, stdout_truncated = _read_tail(bg_process.stdout_file)

    if bg_process.stderr_file and os.path.exists(bg_process.stderr_file):
        stderr_content, stderr_truncated = _read_tail(bg_process.stderr_file)

    if stdout_content:
        response_parts.append(
            f"### stdout\n```\n{stdout_content}\n```\n",
        )
        if stdout_truncated:
            response_parts.append(
                "_stdout truncated to last 64KiB; earlier output omitted._\n",
            )
    if stderr_content:
        response_parts.append(
            f"### stderr\n```\n{stderr_content}\n```\n",
        )
        if stderr_truncated:
            response_parts.append(
                "_stderr truncated to last 64KiB; earlier output omitted._\n",
            )

    if not stdout_content and not stderr_content:
        response_parts.append(
            "\n*No output captured*",
        )

    return ToolResponse(
        content=[TextBlock(type="text", text="\n".join(response_parts))],
    )
