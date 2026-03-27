# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""The shell command tool."""

import asyncio
import locale
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...constant import WORKING_DIR
from ...config.context import get_current_workspace_dir


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


def _read_temp_file(path: str) -> str:
    """Read a temporary output file and return its decoded content."""
    try:
        with open(path, "rb") as f:
            return smart_decode(f.read())
    except OSError:
        return ""


# pylint: disable=too-many-branches, too-many-statements
def _execute_subprocess_sync(
    cmd: str,
    cwd: str,
    timeout: int,
    env: dict | None = None,
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

    Args:
        cmd (`str`):
            The shell command to execute.
        cwd (`str`):
            The working directory for the command execution.
        timeout (`int`):
            The maximum time (in seconds) allowed for the command to run.
        env (`dict | None`):
            Environment variables for the subprocess.

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

    try:
        cmd = _sanitize_win_cmd(cmd)
        wrapped = f'cmd /D /S /C "{cmd}"'

        stdout_fd, stdout_path = tempfile.mkstemp(prefix="copaw_out_")
        stderr_fd, stderr_path = tempfile.mkstemp(prefix="copaw_err_")
        stdout_file = os.fdopen(stdout_fd, "wb")
        stderr_file = os.fdopen(stderr_fd, "wb")

        proc = subprocess.Popen(  # pylint: disable=consider-using-with
            wrapped,
            shell=False,
            stdout=stdout_file,
            stderr=stderr_file,
            text=False,
            cwd=cwd,
            env=env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )

        # Parent copies are no longer needed — the child inherited its own
        # handles via CreateProcess.  Closing here avoids holding the files
        # open longer than necessary.
        stdout_file.close()
        stdout_file = None
        stderr_file.close()
        stderr_file = None

        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_tree_win32(proc.pid)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass

        stdout_str = _read_temp_file(stdout_path)
        stderr_str = _read_temp_file(stderr_path)

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
        for f in (stdout_file, stderr_file):
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


# pylint: disable=too-many-branches, too-many-statements
async def execute_shell_command(
    command: str,
    timeout: int = 60,
    cwd: Optional[Path] = None,
) -> ToolResponse:
    """Execute a shell command and return its output.

    Platform shells: Windows uses cmd.exe; Linux/macOS use /bin/sh or /bin/bash.

    IMPORTANT: Always consider the operating system before choosing commands.

    Args:
        command (`str`):
            The shell command to execute.
        timeout (`int`, defaults to `60`):
            The maximum time (in seconds) allowed for the command to run.
            Default is 60 seconds.
        cwd (`Optional[Path]`, defaults to `None`):
            The working directory for the command execution.
            If None, defaults to WORKING_DIR.

    Returns:
        `ToolResponse`:
            The tool response containing the return code, standard output, and
            standard error of the executed command. If timeout occurs, the
            return code will be -1 and stderr will contain timeout information.
    """

    cmd = (command or "").strip()

    # Use current workspace_dir from context, fallback to WORKING_DIR
    if cwd is not None:
        working_dir = cwd
    else:
        working_dir = get_current_workspace_dir() or WORKING_DIR

    # Ensure the venv Python is on PATH for subprocesses
    env = os.environ.copy()
    python_bin_dir = str(Path(sys.executable).parent)
    existing_path = env.get("PATH", "")
    if existing_path:
        env["PATH"] = python_bin_dir + os.pathsep + existing_path
    else:
        env["PATH"] = python_bin_dir

    try:
        if sys.platform == "win32":
            # Windows: use thread pool to avoid asyncio subprocess limitations
            returncode, stdout_str, stderr_str = await asyncio.to_thread(
                _execute_subprocess_sync,
                cmd,
                str(working_dir),
                timeout,
                env,
            )
        else:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                bufsize=0,
                cwd=str(working_dir),
                env=env,
                start_new_session=True,
            )

            try:
                # Apply timeout to communicate directly; wait()+communicate()
                # can hang if descendants keep stdout/stderr pipes open.
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
                stdout_str = smart_decode(stdout)
                stderr_str = smart_decode(stderr)
                returncode = proc.returncode

            except asyncio.TimeoutError:
                stderr_suffix = (
                    f"⚠️ TimeoutError: The command execution exceeded "
                    f"the timeout of {timeout} seconds. "
                    f"Please consider increasing the timeout value if this command "
                    f"requires more time to complete."
                )
                returncode = -1
                try:
                    # Kill the entire process group so that child processes
                    # spawned by the shell are also terminated.
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGTERM)
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=2)
                    except asyncio.TimeoutError:
                        os.killpg(pgid, signal.SIGKILL)
                        await asyncio.wait_for(proc.wait(), timeout=2)

                    # Drain remaining output.
                    try:
                        stdout, stderr = await asyncio.wait_for(
                            proc.communicate(),
                            timeout=1,
                        )
                    except asyncio.TimeoutError:
                        stdout, stderr = b"", b""
                    stdout_str = smart_decode(stdout)
                    stderr_str = smart_decode(stderr)
                    if stderr_str:
                        stderr_str += f"\n{stderr_suffix}"
                    else:
                        stderr_str = stderr_suffix
                except (ProcessLookupError, OSError):
                    # Process already gone or pgid lookup failed — fall back
                    # to direct kill on the process itself.
                    try:
                        proc.kill()
                        await proc.wait()
                    except (ProcessLookupError, OSError):
                        pass
                    stdout_str = ""
                    stderr_str = stderr_suffix

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

        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=response_text,
                ),
            ],
        )

    except Exception as e:
        return ToolResponse(
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

    return decoded_str.strip("\n")
