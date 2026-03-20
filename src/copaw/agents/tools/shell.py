# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""The shell command tool."""

import asyncio
import locale
import os
import subprocess
import sys
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


def _execute_subprocess_sync(
    cmd: str,
    cwd: str,
    timeout: int,
    env: dict | None = None,
) -> tuple[int, str, str]:
    """Execute subprocess synchronously in a thread.

    This function runs in a separate thread to avoid Windows asyncio
    subprocess limitations.

    Uses ``Popen`` directly instead of ``subprocess.run`` because the
    latter's internal cleanup after a timeout calls ``communicate()``
    **without** a timeout, which hangs when descendant processes still
    hold the pipe handles open (e.g. ``notepad.exe``, ``cmd /k pause``).

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
    try:
        # Disable cmd.exe AutoRun (/D) to prevent spurious stderr
        # from registry-configured startup scripts (e.g. "The system
        # cannot find the path specified.").  /S prevents quote stripping
        # so the inner command is passed through unchanged.
        wrapped = ["cmd", "/D", "/S", "/C", cmd]
        with subprocess.Popen(
            wrapped,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            cwd=cwd,
            env=env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        ) as proc:
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
                return (
                    proc.returncode,
                    smart_decode(stdout),
                    smart_decode(stderr),
                )
            except subprocess.TimeoutExpired:
                _kill_process_tree_win32(proc.pid)

                # Try to drain remaining output after the tree has been killed.
                # The second communicate() should return quickly now that all
                # writers are dead.  Guard with a timeout just in case.
                try:
                    stdout, stderr = proc.communicate(timeout=5)
                    stdout_str = smart_decode(stdout)
                    stderr_str = smart_decode(stderr)
                except (subprocess.TimeoutExpired, OSError, ValueError):
                    stdout_str, stderr_str = "", ""
                    # Force-close pipes to unblock any lingering reader threads
                    # spawned by the first communicate() call.
                    for pipe in (proc.stdout, proc.stderr, proc.stdin):
                        if pipe:
                            try:
                                pipe.close()
                            except OSError:
                                pass
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        pass

                timeout_msg = f"Command execution exceeded the timeout of {timeout} seconds."
                if stderr_str:
                    stderr_str = f"{stderr_str}\n{timeout_msg}"
                else:
                    stderr_str = timeout_msg
                return -1, stdout_str, stderr_str

    except Exception as e:
        return -1, "", str(e)


# pylint: disable=too-many-branches, too-many-statements
async def execute_shell_command(
    command: str,
    timeout: int = 60,
    cwd: Optional[Path] = None,
) -> ToolResponse:
    """Execute given command and return the return code, standard output and
    error within <returncode></returncode>, <stdout></stdout> and
    <stderr></stderr> tags.

    IMPORTANT: Always consider the operating system before choosing commands.

    Args:
        command (`str`):
            The shell command to execute.
        timeout (`int`, defaults to `10`):
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

    # Set working directory
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
                # Handle timeout
                stderr_suffix = (
                    f"⚠️ TimeoutError: The command execution exceeded "
                    f"the timeout of {timeout} seconds. "
                    f"Please consider increasing the timeout value if this command "
                    f"requires more time to complete."
                )
                returncode = -1
                try:
                    proc.terminate()
                    # Wait a bit for graceful termination
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=1)
                    except asyncio.TimeoutError:
                        # Force kill if graceful termination fails
                        proc.kill()
                        await proc.wait()

                    # Avoid hanging forever while draining pipes after timeout.
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
                except ProcessLookupError:
                    stdout_str = ""
                    stderr_str = stderr_suffix

        # Apply output truncation
        # stdout_str = truncate_shell_output(stdout_str)
        # stderr_str = truncate_shell_output(stderr_str)

        # Format the response in a human-friendly way
        if returncode == 0:
            # Success case: just show the output
            if stdout_str:
                response_text = stdout_str
            else:
                response_text = "Command executed successfully (no output)."
        else:
            # Error case: show detailed information
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
