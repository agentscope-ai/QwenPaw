# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def combined_output(self) -> str:
        parts = [
            part.strip() for part in (self.stdout, self.stderr) if part.strip()
        ]
        return "\n".join(parts)


class CommandExecutionError(RuntimeError):
    def __init__(
        self,
        command: Sequence[str],
        message: str,
        *,
        returncode: int | None = None,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.command = list(command)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class ProcessLaunchError(RuntimeError):
    def __init__(
        self,
        command: Sequence[str],
        message: str,
    ) -> None:
        super().__init__(message)
        self.command = list(command)


@dataclass(frozen=True)
class ShutdownResult:
    command: list[str]
    pid: int
    exited: bool
    terminated_gracefully: bool
    killed: bool
    timed_out: bool
    returncode: int | None


class _ThreadedProcessStdout:
    """Async adapter for a blocking subprocess stdout stream."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream

    async def readline(self) -> bytes:
        return await asyncio.to_thread(self._stream.readline)


class ThreadedProcess:
    """Minimal async-compatible wrapper around subprocess.Popen."""

    def __init__(self, process: subprocess.Popen[Any]) -> None:
        self._process = process
        self.stdout = (
            _ThreadedProcessStdout(process.stdout)
            if process.stdout is not None
            else None
        )

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def returncode(self) -> int | None:
        return self._process.poll()

    async def wait(self) -> int:
        return await asyncio.to_thread(self._process.wait)

    def terminate(self) -> None:
        self._process.terminate()

    def kill(self) -> None:
        self._process.kill()

    def is_alive(self) -> bool:
        return self.returncode is None

    def join(self, timeout: float | None = None) -> int | None:
        try:
            return self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def close(self) -> None:
        return None


class ManagedProcess:
    """Unified wrapper for long-lived processes across launch modes."""

    def __init__(
        self,
        process: Any,
        *,
        command: Sequence[str],
        owns_process_group: bool,
        creation_mode: str,
    ) -> None:
        self._process = process
        self.command = list(command)
        self.owns_process_group = owns_process_group
        self.creation_mode = creation_mode
        self.platform_name = os.name

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def returncode(self) -> int | None:
        if hasattr(self._process, "returncode"):
            return self._process.returncode
        return getattr(self._process, "exitcode", None)

    @property
    def stdout(self) -> Any | None:
        return getattr(self._process, "stdout", None)

    async def wait(self) -> int:
        if hasattr(self._process, "wait"):
            return await self._process.wait()

        return await asyncio.to_thread(self._wait_via_join)

    def _wait_via_join(self) -> int:
        join = getattr(self._process, "join", None)
        if join is None:
            raise RuntimeError("Managed process does not support waiting")
        join()
        returncode = self.returncode
        if returncode is None:
            raise RuntimeError("Managed process did not exit")
        return returncode

    def terminate(self) -> None:
        if self.owns_process_group and self.platform_name != "nt":
            with suppress(ProcessLookupError):
                os.killpg(os.getpgid(self.pid), signal.SIGTERM)
            return

        with suppress(ProcessLookupError):
            self._process.terminate()

    def kill(self) -> None:
        if self.owns_process_group and self.platform_name != "nt":
            with suppress(ProcessLookupError):
                os.killpg(os.getpgid(self.pid), signal.SIGKILL)
            return

        with suppress(ProcessLookupError):
            self._process.kill()

    def is_alive(self) -> bool:
        if hasattr(self._process, "is_alive"):
            return bool(self._process.is_alive())
        return self.returncode is None

    def join(self, timeout: float | None = None) -> int | None:
        if hasattr(self._process, "join"):
            return self._process.join(timeout=timeout)
        return self.returncode

    def close(self) -> None:
        if hasattr(self._process, "close"):
            self._process.close()


def run_command(
    command: Sequence[str],
    *,
    timeout: int | float | None = 10,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = True,
) -> CommandResult:
    command_list = list(command)
    try:
        result = subprocess.run(
            command_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
            cwd=str(cwd) if cwd is not None else None,
            env=dict(env) if env is not None else None,
        )
    except FileNotFoundError as exc:
        raise CommandExecutionError(
            command_list,
            f"Command executable not found: {command_list[0]}",
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise CommandExecutionError(
            command_list,
            f"Failed to run command: {exc}",
        ) from exc

    command_result = CommandResult(
        command=command_list,
        returncode=result.returncode,
        stdout=result.stdout or "",
        stderr=result.stderr or "",
    )
    if check and command_result.returncode != 0:
        raise CommandExecutionError(
            command_list,
            command_result.combined_output
            or f"Command exited with code {command_result.returncode}",
            returncode=command_result.returncode,
            stdout=command_result.stdout,
            stderr=command_result.stderr,
        )
    return command_result


async def run_command_async(
    command: Sequence[str],
    *,
    timeout: int | float | None = 10,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = True,
) -> CommandResult:
    """Run a short-lived command without relying on asyncio subprocess APIs.

    This helper intentionally delegates to `subprocess.run` in a worker
    thread so it remains usable on Windows event loops where
    `asyncio.create_subprocess_exec` may raise `NotImplementedError`.
    """
    return await asyncio.to_thread(
        run_command,
        command,
        timeout=timeout,
        cwd=cwd,
        env=env,
        check=check,
    )


async def start_process_async(
    command: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    **process_kwargs: Any,
) -> ManagedProcess:
    """Start a long-lived process with a Windows-safe fallback path."""
    command_list = list(command)
    popen_kwargs = dict(process_kwargs)
    if cwd is not None:
        popen_kwargs["cwd"] = str(cwd)
    if env is not None:
        popen_kwargs["env"] = dict(env)
    owns_process_group = bool(
        os.name != "nt" and popen_kwargs.get("start_new_session"),
    )

    try:
        process = await asyncio.create_subprocess_exec(
            *command_list,
            **popen_kwargs,
        )
        return ManagedProcess(
            process,
            command=command_list,
            owns_process_group=owns_process_group,
            creation_mode="asyncio",
        )
    except NotImplementedError:
        if os.name != "nt":
            raise
        return await asyncio.to_thread(
            _start_threaded_process,
            command_list,
            popen_kwargs,
            owns_process_group,
        )
    except FileNotFoundError as exc:
        raise ProcessLaunchError(
            command_list,
            f"Command executable not found: {command_list[0]}",
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProcessLaunchError(
            command_list,
            f"Failed to start process: {exc}",
        ) from exc


def start_multiprocessing_process(
    process: Any,
    *,
    command: Sequence[str],
    creation_mode: str = "multiprocessing",
) -> ManagedProcess:
    command_list = list(command)
    try:
        process.start()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProcessLaunchError(
            command_list,
            f"Failed to start process: {exc}",
        ) from exc

    return ManagedProcess(
        process,
        command=command_list,
        owns_process_group=False,
        creation_mode=creation_mode,
    )


def _start_threaded_process(
    command: list[str],
    popen_kwargs: dict[str, Any],
    owns_process_group: bool,
) -> ManagedProcess:
    try:
        process = subprocess.Popen(  # pylint: disable=consider-using-with
            command,
            **popen_kwargs,
        )
    except FileNotFoundError as exc:
        raise ProcessLaunchError(
            command,
            f"Command executable not found: {command[0]}",
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProcessLaunchError(
            command,
            f"Failed to start process: {exc}",
        ) from exc
    return ManagedProcess(
        ThreadedProcess(process),
        command=command,
        owns_process_group=owns_process_group,
        creation_mode="threaded",
    )


async def shutdown_process(
    process: ManagedProcess,
    *,
    graceful_timeout: float = 5.0,
    kill_timeout: float | None = None,
) -> ShutdownResult:
    if process.returncode is not None:
        return ShutdownResult(
            command=process.command,
            pid=process.pid,
            exited=True,
            terminated_gracefully=False,
            killed=False,
            timed_out=False,
            returncode=process.returncode,
        )

    process.terminate()
    try:
        returncode = await asyncio.wait_for(
            process.wait(),
            timeout=graceful_timeout,
        )
        return ShutdownResult(
            command=process.command,
            pid=process.pid,
            exited=True,
            terminated_gracefully=True,
            killed=False,
            timed_out=False,
            returncode=returncode,
        )
    except asyncio.TimeoutError:
        process.kill()

    try:
        if kill_timeout is None:
            returncode = await process.wait()
        else:
            returncode = await asyncio.wait_for(
                process.wait(),
                timeout=kill_timeout,
            )
        return ShutdownResult(
            command=process.command,
            pid=process.pid,
            exited=True,
            terminated_gracefully=False,
            killed=True,
            timed_out=False,
            returncode=returncode,
        )
    except asyncio.TimeoutError:
        return ShutdownResult(
            command=process.command,
            pid=process.pid,
            exited=False,
            terminated_gracefully=False,
            killed=True,
            timed_out=True,
            returncode=process.returncode,
        )


def shutdown_process_sync(
    process: ManagedProcess,
    *,
    graceful_timeout: float = 5.0,
    kill_timeout: float | None = 1.0,
) -> ShutdownResult:
    if process.returncode is not None:
        return ShutdownResult(
            command=process.command,
            pid=process.pid,
            exited=True,
            terminated_gracefully=False,
            killed=False,
            timed_out=False,
            returncode=process.returncode,
        )

    process.terminate()
    if _wait_for_process_exit(process, graceful_timeout):
        return ShutdownResult(
            command=process.command,
            pid=process.pid,
            exited=True,
            terminated_gracefully=True,
            killed=False,
            timed_out=False,
            returncode=process.returncode,
        )

    process.kill()
    if _wait_for_process_exit(process, kill_timeout):
        return ShutdownResult(
            command=process.command,
            pid=process.pid,
            exited=True,
            terminated_gracefully=False,
            killed=True,
            timed_out=False,
            returncode=process.returncode,
        )

    return ShutdownResult(
        command=process.command,
        pid=process.pid,
        exited=False,
        terminated_gracefully=False,
        killed=True,
        timed_out=True,
        returncode=process.returncode,
    )


def _wait_for_process_exit(
    process: ManagedProcess,
    timeout: float | None,
) -> bool:
    if not process.is_alive():
        process.join(timeout=0)
        return True

    if timeout is None:
        while process.is_alive():
            time.sleep(0.1)
        process.join(timeout=0)
        return True

    deadline = time.monotonic() + timeout
    while True:
        if not process.is_alive():
            process.join(timeout=0)
            return True
        if not _is_pid_running(process.pid, process.platform_name):
            process.join(timeout=0)
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.1, remaining))
    if not process.is_alive():
        process.join(timeout=0)
        return True
    return not _is_pid_running(process.pid, process.platform_name)


def _is_pid_running(
    pid: int,
    platform_name: str,
) -> bool:
    if platform_name == "nt":
        try:
            output = subprocess.check_output(
                ["tasklist", "/fi", f"PID eq {pid}"],
                stderr=subprocess.STDOUT,
                text=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
        return str(pid) in output

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
