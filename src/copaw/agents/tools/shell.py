# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""The shell command tool."""

import asyncio
import locale
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

from agentscope.tool import ToolResponse
from agentscope.message import TextBlock

from copaw.constant import WORKING_DIR

logger = logging.getLogger(__name__)

# Server-like command patterns that should use background_process instead
_SERVER_PATTERNS = [
    "http.server",
    "simplehttpserver",
    "flask run",
    "django runserver",
    "uvicorn",
    "gunicorn",
    "npm run dev",
    "npm start",
    "yarn dev",
    "yarn start",
    "webpack --watch",
    "nodemon",
    "tsc --watch",
    "nginx",
    "apache",
    "mongod",
    "redis-server",
    "postgres",
    "live-server",
    "http-server",
]


def _execute_subprocess_sync(
    cmd: str,
    cwd: str,
    timeout: int,
) -> tuple[int, str, str]:
    """Execute subprocess synchronously in a thread.

    This function runs in a separate thread to avoid Windows asyncio
    subprocess limitations.

    Args:
        cmd (`str`):
            The shell command to execute.
        cwd (`str`):
            The working directory for the command execution.
        timeout (`int`):
            The maximum time (in seconds) allowed for the command to run.

    Returns:
        `tuple[int, str, str]`:
            A tuple containing the return code, standard output, and
            standard error of the executed command. If timeout occurs, the
            return code will be -1 and stderr will contain timeout information.
    """
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
            encoding=locale.getpreferredencoding(False) or "utf-8",
            errors="replace",
            check=True,
        )
        return (
            result.returncode,
            result.stdout.strip("\n"),
            result.stderr.strip("\n"),
        )
    except subprocess.TimeoutExpired:
        return (
            -1,
            "",
            f"Command execution exceeded the timeout of {timeout} seconds.",
        )
    except Exception as e:
        return -1, "", str(e)


# pylint: disable=too-many-branches, too-many-statements
async def execute_shell_command(
    command: str,
    timeout: int = 60,
    cwd: Optional[Path] = None,
) -> ToolResponse:
    """Execute a shell command and wait for it to complete, then return output.

    ⚠️ IMPORTANT - When to use this tool vs start_background_process:

    **Use THIS tool (execute_shell_command) for:**
    - Quick commands that complete quickly (ls, cat, grep, git status, etc.)
    - Commands where you NEED the output to proceed
    - File operations (copy, move, delete)
    - Package installations (pip install, npm install)
    - Build/test commands that finish in reasonable time

    **Use start_background_process instead for:**
    - HTTP servers (python -m http.server, nginx, apache)
    - Development servers (npm run dev, flask run, django runserver)
    - File watchers (webpack --watch, nodemon)
    - Long-running daemons or services
    - Any command that runs until manually stopped

    The key question: Does the command finish by itself?
    - YES → Use execute_shell_command
    - NO (runs until stopped) → Use start_background_process

    Args:
        command (`str`):
            The shell command to execute.
        timeout (`int`, defaults to `60`):
            The maximum time (in seconds) allowed for the command to run.
            Default is 60 seconds. For longer operations, increase timeout
            or consider if start_background_process is more appropriate.
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

    # Detect server-like commands that should use background_process instead
    cmd_lower = cmd.lower()
    # Tokenize command to detect generic 'serve' as a standalone word only
    cmd_tokens = cmd_lower.split()
    is_server_like = (
        any(pattern in cmd_lower for pattern in _SERVER_PATTERNS)
        or "serve" in cmd_tokens
    )

    if is_server_like:
        logger.warning(
            "Detected server-like command that may run indefinitely. "
            "Consider using start_background_process instead.",
        )

    # Set working directory
    working_dir = cwd if cwd is not None else WORKING_DIR

    try:
        if sys.platform == "win32":
            # Windows: use thread pool to avoid asyncio subprocess limitations
            returncode, stdout_str, stderr_str = await asyncio.to_thread(
                _execute_subprocess_sync,
                cmd,
                str(working_dir),
                timeout,
            )

            # Handle Windows timeout with server-like command detection
            if returncode == -1 and "timeout" in stderr_str.lower():
                if is_server_like:
                    stderr_str = (
                        f"⚠️ TimeoutError: The command appears to be a server or "
                        f"long-running process that exceeded the {timeout} second timeout.\n\n"
                        f"💡 This command seems to run indefinitely. "
                        f"Use start_background_process() instead:\n"
                        f'   start_background_process(command="<your_command_here>")\n\n'
                        f"This will start it in the background without blocking."
                    )
        else:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                bufsize=0,
                cwd=str(working_dir),
            )

            try:
                # Apply timeout to communicate directly; wait()+communicate()
                # can hang if descendants keep stdout/stderr pipes open.
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
                encoding = locale.getpreferredencoding(False) or "utf-8"
                stdout_str = stdout.decode(encoding, errors="replace").strip(
                    "\n",
                )
                stderr_str = stderr.decode(encoding, errors="replace").strip(
                    "\n",
                )
                returncode = proc.returncode

            except asyncio.TimeoutError:
                # Handle timeout
                if is_server_like:
                    stderr_suffix = (
                        f"⚠️ TimeoutError: The command appears to be a server or "
                        f"long-running process that exceeded the {timeout} second timeout.\n\n"
                        f"💡 This command seems to run indefinitely. "
                        f"Use start_background_process() instead:\n"
                        f'   start_background_process(command="<your_command_here>")\n\n'
                        f"This will start it in the background without blocking."
                    )
                else:
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
                    encoding = locale.getpreferredencoding(False) or "utf-8"
                    stdout_str = stdout.decode(
                        encoding,
                        errors="replace",
                    ).strip(
                        "\n",
                    )
                    stderr_str = stderr.decode(
                        encoding,
                        errors="replace",
                    ).strip(
                        "\n",
                    )
                    if stderr_str:
                        stderr_str += f"\n{stderr_suffix}"
                    else:
                        stderr_str = stderr_suffix
                except ProcessLookupError:
                    stdout_str = ""
                    stderr_str = stderr_suffix

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
