# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""The shell command tool."""

import asyncio
import locale
from pathlib import Path
from typing import Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from copaw.constant import WORKING_DIR


def _safe_working_dir(cwd: Optional[Path]) -> Path:
    """Return a valid directory path for subprocess cwd across platforms."""
    if cwd is not None:
        try:
            p = Path(cwd)
            if p.exists() and p.is_dir():
                return p
        except Exception:
            return Path.cwd()
        return Path.cwd()

    try:
        p = Path(WORKING_DIR)
        if p.exists() and p.is_dir():
            return p
    except Exception:
        pass

    return Path.cwd()


def _decode_output(b: bytes) -> str:
    enc = locale.getpreferredencoding(False) or "utf-8"
    return b.decode(enc, errors="replace").strip("\n")


# pylint: disable=too-many-branches, too-many-statements
async def execute_shell_command(
    command: str,
    timeout: int = 60,
    cwd: Optional[Path] = None,
) -> ToolResponse:
    """Execute given command and return the return code, standard output and
    error within <returncode></returncode>, <stdout></stdout> and
    <stderr></stderr> tags.

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
    if not cmd:
        return ToolResponse(
            content=[TextBlock(type="text", text="No command provided.")],
        )

    working_dir = _safe_working_dir(cwd)

    try:
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                bufsize=0,
                cwd=str(working_dir),
            )
        except OSError:
            # Windows can raise [WinError 267] for malformed/invalid cwd.
            # Fall back to current working directory.
            working_dir = Path.cwd()
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                bufsize=0,
                cwd=str(working_dir),
            )

        stdout_str = ""
        stderr_str = ""
        returncode = 0

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
            stdout_str = _decode_output(stdout)
            stderr_str = _decode_output(stderr)
            returncode = proc.returncode

        except asyncio.TimeoutError:
            stderr_suffix = (
                f"⚠️ TimeoutError: The command execution exceeded "
                f"the timeout of {timeout} seconds. "
                f"Please consider increasing the timeout value if this command "
                f"requires more time to complete."
            )
            returncode = -1

            # Try graceful termination first
            try:
                proc.terminate()
            except ProcessLookupError:
                proc = None

            stdout = b""
            stderr = b""
            if proc is not None:
                try:
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(),
                        timeout=1,
                    )
                except asyncio.TimeoutError:
                    # Force kill if graceful termination fails
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    stdout, stderr = await proc.communicate()

            stdout_str = _decode_output(stdout)
            stderr_str = _decode_output(stderr)

            if stderr_str:
                stderr_str = f"{stderr_str}\n{stderr_suffix}"
            else:
                stderr_str = stderr_suffix

        # Format the response in a human-friendly way
        if returncode == 0:
            response_text = (
                stdout_str or "Command executed successfully (no output)."
            )
        else:
            response_parts = [f"Command failed with exit code {returncode}."]
            if stdout_str:
                response_parts.append(f"\n[stdout]\n{stdout_str}")
            if stderr_str:
                response_parts.append(f"\n[stderr]\n{stderr_str}")
            response_text = "".join(response_parts)

        return ToolResponse(
            content=[TextBlock(type="text", text=response_text)],
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
