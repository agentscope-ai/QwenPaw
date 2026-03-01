# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long
"""The shell command tool."""

import asyncio
import locale
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from agentscope.tool import ToolResponse
from agentscope.message import TextBlock

from copaw.constant import WORKING_DIR


def _normalize_command(cmd: str) -> tuple[str, str | None]:
    """Normalize shell wrappers for cross-platform execution."""
    if os.name != "nt":
        return cmd, None

    # LLMs often emit Linux-style wrappers on Windows. If bash is not
    # available, unwrap `bash -lc "..."` and run the inner command directly.
    if cmd.strip().lower().startswith("bash -lc") and shutil.which("bash") is None:
        try:
            parts = shlex.split(cmd, posix=True)
            if len(parts) >= 3 and parts[0].lower() == "bash" and parts[1] == "-lc":
                return (
                    parts[2],
                    "bash is unavailable on Windows, executed inner command directly.",
                )
        except ValueError:
            pass

    return cmd, None


def _run_shell_command_sync(
    cmd: str,
    cwd: Path,
    timeout: int,
) -> tuple[int, bytes, bytes, str | None]:
    """Execute command in a worker thread for compatibility."""
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd),
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout or b"", proc.stderr or b"", None
    except subprocess.TimeoutExpired as exc:
        timeout_msg = (
            f"⚠️ TimeoutError: The command execution exceeded the timeout of {timeout} seconds. "
            "Please consider increasing the timeout value if this command requires more time to complete."
        )
        return -1, exc.stdout or b"", exc.stderr or b"", timeout_msg


# pylint: disable=too-many-branches
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

    notices: list[str] = []

    # Set and validate working directory
    try:
        working_dir = Path(cwd).expanduser() if cwd is not None else WORKING_DIR
    except Exception:
        working_dir = WORKING_DIR
        notices.append("Invalid cwd provided, fallback to default working directory.")

    if not working_dir.exists() or not working_dir.is_dir():
        notices.append(
            f"Provided cwd does not exist or is not a directory: {working_dir}. "
            f"Fallback to {WORKING_DIR}.",
        )
        working_dir = WORKING_DIR

    cmd, normalize_notice = _normalize_command(cmd)
    if normalize_notice:
        notices.append(normalize_notice)

    try:
        returncode, stdout, stderr, timeout_msg = await asyncio.to_thread(
            _run_shell_command_sync,
            cmd,
            working_dir,
            timeout,
        )

        encoding = locale.getpreferredencoding(False) or "utf-8"
        stdout_str = stdout.decode(encoding, errors="replace").strip("\n")
        stderr_str = stderr.decode(encoding, errors="replace").strip("\n")
        if timeout_msg:
            if stderr_str:
                stderr_str += f"\n{timeout_msg}"
            else:
                stderr_str = timeout_msg

        # Format the response in a human-friendly way
        notice_prefix = ""
        if notices:
            notice_prefix = "\n".join(f"[notice] {n}" for n in notices) + "\n\n"

        if returncode == 0:
            # Success case: just show the output
            if stdout_str:
                response_text = f"{notice_prefix}{stdout_str}"
            else:
                response_text = f"{notice_prefix}Command executed successfully (no output)."
        else:
            # Error case: show detailed information
            response_parts = [f"{notice_prefix}Command failed with exit code {returncode}."]
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
        detail = str(e) or repr(e)
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "Error: Shell command execution failed due to\n"
                        f"{e.__class__.__name__}: {detail}"
                    ),
                ),
            ],
        )
