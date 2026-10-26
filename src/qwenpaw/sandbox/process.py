# -*- coding: utf-8 -*-
"""Duplex process sessions using the existing sandbox factory and policies."""

from __future__ import annotations

import asyncio
import os
import shlex
import signal
import sys
import tempfile
from contextlib import AsyncExitStack, ExitStack
from pathlib import Path

import psutil

from ..utils.io_utils import run_sync_io
from .bubblewrap_sandbox import BubblewrapSandbox
from .config import SandboxConfig, create_sandbox
from .linux_sandbox import LinuxSandbox, _generate_sandbox_script
from .local_sandbox import NoneSandbox
from .macos_sandbox import MacOSSandbox
from .windows_appcontainer_sandbox import WindowsAppContainerSandbox
from .windows_appcontainer_sandbox import WindowsSandboxProcess
from .windows_elevated_sandbox import WindowsElevatedSandbox
from .windows_elevated_sandbox import _create_process_with_token
from .windows_unelevated_sandbox import WindowsUnelevatedSandbox
from .windows_unelevated_sandbox import _create_process_as_user


if sys.platform == f"win32":
    import msvcrt
else:
    msvcrt = None


class SandboxProcess:
    """Own a sandbox, a child process and asynchronous binary IPC.

    Startup is shielded until ownership transfers, so cancelling a thread
    that is creating a native process cannot orphan that process.
    """

    def __init__(
        self,
        config: SandboxConfig,
        command: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        limit: int,
    ) -> None:
        self.config: SandboxConfig = config
        self.command = command
        self.cwd = cwd
        self.env = {**env, **config.env_vars}
        self.limit = limit
        self.process = None
        self.input = None
        self.output = None
        self._blocking_pipes = False
        self._stack = AsyncExitStack()
        self._files = ExitStack()
        self._stack.push_async_callback(run_sync_io, self._files.close)

    async def __aenter__(self):
        startup = asyncio.create_task(self._start())
        try:
            await asyncio.shield(startup)
        except BaseException:
            try:
                await startup
            finally:
                await self.__aexit__(None, None, None)
            raise
        return self

    async def _start(self) -> None:
        sandbox = await run_sync_io(create_sandbox, self.config)
        await self._stack.enter_async_context(sandbox)
        if isinstance(
            sandbox,
            (
                WindowsAppContainerSandbox,
                WindowsElevatedSandbox,
                WindowsUnelevatedSandbox,
            ),
        ):
            await asyncio.to_thread(self._start_windows, sandbox)
            return
        command = await run_sync_io(self._prepare_command, sandbox)
        self.process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=self.cwd,
            env=self.env,
            start_new_session=sys.platform != f"win32",
            limit=self.limit,
        )
        self.input = self.process.stdin
        self.output = self.process.stdout

    def _prepare_command(self, sandbox) -> list[str]:
        # Policy compilation stays inside the sandbox package. No caller
        # rewrites backend profiles or bypasses the factory's dispatch.
        # pylint: disable=protected-access
        if isinstance(sandbox, NoneSandbox):
            return self.command
        if isinstance(sandbox, MacOSSandbox):
            return [
                f"sandbox-exec",
                f"-p",
                sandbox._compile_seatbelt_profile(),
                *self.command,
            ]
        if isinstance(sandbox, BubblewrapSandbox):
            return [
                sandbox._find_bwrap(),
                *sandbox._build_bwrap_args(
                    f"exec {shlex.join(self.command)}",
                    self.cwd,
                ),
            ]
        if isinstance(sandbox, LinuxSandbox):
            script = _generate_sandbox_script(
                sandbox.config,
                f"exec {shlex.join(self.command)}",
                self.cwd,
                sandbox._abi_version,
            )
            directory = self._files.enter_context(
                tempfile.TemporaryDirectory(prefix=f"qwenpaw-landlock-"),
            )
            path = Path(directory) / f"launch.py"
            path.write_text(script, encoding=f"utf-8")
            return [self.command[0], str(path)]
        raise TypeError(
            f"Unsupported process backend: {type(sandbox).__name__}",
        )

    def _start_windows(self, sandbox) -> None:
        # pylint: disable=protected-access
        self._blocking_pipes = True
        child_input, host_input = os.pipe()
        self.input = self._files.enter_context(os.fdopen(host_input, f"wb"))
        reader = self._files.enter_context(os.fdopen(child_input, f"rb"))
        host_output, child_output = os.pipe()
        self.output = self._files.enter_context(os.fdopen(host_output, f"rb"))
        writer = self._files.enter_context(os.fdopen(child_output, f"wb"))
        try:
            if isinstance(sandbox, WindowsAppContainerSandbox):
                self.process = sandbox.spawn_process(
                    self.command,
                    cwd=self.cwd,
                    env=self.env,
                    log_handle=writer,
                    stdin_handle=reader,
                )
            else:
                handles = tuple(
                    msvcrt.get_osfhandle(stream.fileno())
                    for stream in (reader, writer, writer)
                )
                for handle in set(handles):
                    os.set_handle_inheritable(handle, True)
                try:
                    if isinstance(sandbox, WindowsElevatedSandbox):
                        spawn = _create_process_with_token
                        token = sandbox._instance.h_token
                    else:
                        spawn = _create_process_as_user
                        token = sandbox._h_token
                    pid, process, _, _, job = spawn(
                        token,
                        self.command,
                        self.cwd,
                        self.env,
                        stdio=handles,
                    )
                    self.process = WindowsSandboxProcess(pid, process, job)
                finally:
                    for handle in set(handles):
                        os.set_handle_inheritable(handle, False)
        finally:
            reader.close()
            writer.close()

    async def write(self, data: bytes) -> None:
        """Write and flush one packet without blocking the event loop."""
        if self._blocking_pipes:
            await asyncio.to_thread(self._write_sync, data)
        else:
            self.input.write(data)
            await self.input.drain()

    def _write_sync(self, data: bytes) -> None:
        self.input.write(data)
        self.input.flush()

    async def readline(self) -> bytes:
        """Read at most one bounded protocol line."""
        if self._blocking_pipes:
            return await asyncio.to_thread(
                self.output.readline,
                self.limit + 1,
            )
        return await self.output.readline()

    async def __aexit__(self, *_args):
        try:
            if self.process is not None:
                if self._blocking_pipes:
                    await asyncio.to_thread(self.process.kill)
                    await asyncio.to_thread(self.process.wait, 5)
                else:
                    try:
                        if sys.platform == f"win32":
                            await asyncio.to_thread(self._kill_windows_tree)
                        else:
                            os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await self.process.communicate()
        finally:
            await self._stack.aclose()

    def _kill_windows_tree(self) -> None:
        # Unrestricted processes do not have a native sandbox Job Object.
        try:
            root = psutil.Process(self.process.pid)
            for child in reversed(root.children(recursive=True)):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            root.kill()
        except psutil.NoSuchProcess:
            pass
