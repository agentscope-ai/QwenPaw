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


def _collapse_newlines_outside_quotes(cmd: str) -> str:
    r"""Collapse newlines outside quoted strings; preserve those inside.

    Used only on Unix where sh/bash correctly handles newlines in quotes.
    Handles backslash-newline (line continuation) by removing both chars,
    and treats single-quoted content as fully literal per POSIX.
    """
    result: list[str] = []
    in_single_quote = False
    in_double_quote = False
    i = 0
    length = len(cmd)

    while i < length:
        char = cmd[i]

        # Toggle quote state
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            result.append(char)
            i += 1
            continue

        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            result.append(char)
            i += 1
            continue

        # Inside single quotes: everything is literal (POSIX)
        if in_single_quote:
            result.append(char)
            i += 1
            continue

        # Backslash-newline (line continuation): remove both chars
        if char == "\\" and i + 1 < length and cmd[i + 1] in ("\r", "\n"):
            i += 2
            # \r\n sequence: skip the \n as well
            if i < length and cmd[i - 1] == "\r" and cmd[i] == "\n":
                i += 1
            continue

        # Backslash escape (non-newline): keep both chars
        if char == "\\" and i + 1 < length:
            result.append(char)
            result.append(cmd[i + 1])
            i += 2
            continue

        # Newlines
        if char in ("\r", "\n"):
            if in_double_quote:
                # Preserve newlines inside double quotes
                result.append(char)
            else:
                # Collapse \r\n as a single space
                if char == "\r" and i + 1 < length and cmd[i + 1] == "\n":
                    i += 1
                result.append(" ")
            i += 1
            continue

        result.append(char)
        i += 1

    return "".join(result)


def _collapse_embedded_newlines(cmd: str) -> str:
    r"""Replace embedded newline characters with spaces in a command string.

    LLMs produce tool-call arguments in JSON where ``\n`` is parsed as an
    actual newline character.  In the original shell command the user
    intended the *literal* two-character sequence ``\n`` (e.g. inside a
    ``--content`` flag), but after JSON decoding it becomes a real line
    break.  When passed to a shell:

    * **Windows** ``cmd.exe`` truncates the command at the first newline
      regardless of quoting context — this is a hard limitation of the
      Windows command processor.  All newlines must be collapsed.
    * **Unix** ``sh -c`` treats an unquoted newline as a command separator,
      but correctly handles newlines inside quoted strings.

    On Unix/macOS, newlines inside quoted strings are preserved so that
    downstream commands receive the correct multi-line content (e.g.
    ``--text "Hello\nWorld"``).  On Windows, all newlines are collapsed
    to ensure the command at least executes successfully.
    """
    if "\n" not in cmd:
        return cmd
    if sys.platform == "win32":
        # cmd.exe truncates at newlines regardless of quoting — must
        # collapse all to ensure the command executes at all.
        return cmd.replace("\r\n", " ").replace("\n", " ")
    return _collapse_newlines_outside_quotes(cmd)


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
    timeout: float,
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

    .. note::

       Callers must pre-process *cmd* through
       :func:`_collapse_embedded_newlines` before passing it here.
       ``execute_shell_command`` already does this.

    Args:
        cmd (`str`):
            The shell command to execute (must not contain embedded
            newlines — see note above).
        cwd (`str`):
            The working directory for the command execution.
        timeout (`float`):
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

        stdout_fd, stdout_path = tempfile.mkstemp(prefix="qwenpaw_out_")
        stderr_fd, stderr_path = tempfile.mkstemp(prefix="qwenpaw_err_")
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
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW,
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
    timeout: float = 60.0,
    cwd: Optional[Path] = None,
) -> ToolResponse:
    """Execute a shell command and return its output.

    Platform shells: Windows uses cmd.exe; Linux/macOS use /bin/sh or /bin/bash.

    IMPORTANT: Always consider the operating system before choosing commands.

    Args:
        command (`str`):
            The shell command to execute.
        timeout (`float`, defaults to `60.0`):
            The maximum time (in seconds) allowed for the command to run.
            Default is 60.0 seconds.
        cwd (`Optional[Path]`, defaults to `None`):
            The working directory for the command execution.
            If None, defaults to WORKING_DIR.

    Returns:
        `ToolResponse`:
            The tool response containing the return code, standard output, and
            standard error of the executed command. If timeout occurs, the
            return code will be -1 and stderr will contain timeout information.
    """

    cmd = _collapse_embedded_newlines((command or "").strip())

    if isinstance(timeout, str):
        try:
            timeout = float(timeout)
        except (ValueError, TypeError):
            timeout = 60.0

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
