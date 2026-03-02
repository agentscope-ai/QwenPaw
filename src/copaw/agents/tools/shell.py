# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""The shell command tool."""

import asyncio
import locale
import os
import shlex
import signal
import subprocess
from pathlib import Path
from typing import Optional

from agentscope.tool import ToolResponse
from agentscope.message import TextBlock

from copaw.constant import WORKING_DIR


def _decode_output(output: bytes) -> str:
    """Decode process output using preferred locale with fallback."""
    encoding = locale.getpreferredencoding(False) or "utf-8"
    return output.decode(encoding, errors="replace").strip("\n")


def _resolve_working_dir(cwd: Optional[Path]) -> Path:
    """Resolve and validate working directory to stay within WORKING_DIR."""
    root = WORKING_DIR.resolve()
    candidate = (cwd if cwd is not None else WORKING_DIR).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(
            f"Working directory must be under {root}, got: {candidate}",
        )
    return candidate


async def _terminate_process_tree(
    proc: asyncio.subprocess.Process,
) -> None:
    """Terminate process and its children best-effort."""
    if proc.returncode is not None:
        return

    try:
        if os.name != "nt":
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
    except ProcessLookupError:
        return

    try:
        await asyncio.wait_for(proc.wait(), timeout=1)
        return
    except asyncio.TimeoutError:
        pass
    except ProcessLookupError:
        return

    try:
        if os.name != "nt":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except ProcessLookupError:
        return

    await proc.wait()


# pylint: disable=too-many-branches,too-many-return-statements,too-many-statements
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
    if not cmd:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="Error: command must be a non-empty string.",
                ),
            ],
        )
    if any(ch in cmd for ch in ("\x00", "\n", "\r")):
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="Error: command contains invalid control characters.",
                ),
            ],
        )
    try:
        # Use exec form to avoid shell expansion/injection via metacharacters.
        args = shlex.split(cmd, posix=os.name != "nt")
    except ValueError as exc:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: invalid command syntax: {exc}",
                ),
            ],
        )
    if not args:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="Error: command must include an executable.",
                ),
            ],
        )

    # Set working directory
    try:
        working_dir = _resolve_working_dir(cwd)
    except ValueError as exc:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=f"Error: {exc}",
                ),
            ],
        )

    try:
        popen_kwargs = {}
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            bufsize=0,
            cwd=str(working_dir),
            **popen_kwargs,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
            stdout_str = _decode_output(stdout)
            stderr_str = _decode_output(stderr)
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
                await _terminate_process_tree(proc)
                # Read remaining output directly from streams instead of
                # calling communicate() again (it can only be called once).
                stdout = await proc.stdout.read() if proc.stdout else b""
                stderr = await proc.stderr.read() if proc.stderr else b""
                stdout_str = _decode_output(stdout)
                stderr_str = _decode_output(stderr)
                if stderr_str:
                    stderr_str += f"\n{stderr_suffix}"
                else:
                    stderr_str = stderr_suffix
            except ProcessLookupError:
                stdout_str = ""
                stderr_str = stderr_suffix
        except asyncio.CancelledError:
            await _terminate_process_tree(proc)
            raise

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
