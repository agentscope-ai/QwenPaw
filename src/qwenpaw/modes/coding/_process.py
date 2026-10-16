# -*- coding: utf-8 -*-
"""Launch a fresh CPython worker using existing native sandbox policies."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import signal
import sys
import tempfile
from contextlib import AsyncExitStack
from pathlib import Path

import psutil

from ...sandbox import BubblewrapSandbox, MacOSSandbox
from ...sandbox import MountSpec, SandboxConfig, SandboxMode
from ...sandbox import WindowsAppContainerSandbox

MAX_MESSAGE_BYTES = 16 * 1024 * 1024


class WorkerProcess:
    """Own the isolated process, its IPC and bounded execution lifetime."""

    def __init__(self) -> None:
        self.stack = AsyncExitStack()
        self.process = None
        self.input = None
        self.output = None
        self.send_lock = asyncio.Lock()

    async def __aenter__(self):
        try:
            directory = self.stack.enter_context(
                tempfile.TemporaryDirectory(prefix="qwenpaw-code-"),
            )
            directory = str(Path(directory).resolve())
            worker = Path(directory) / "worker.py"
            worker.write_bytes(
                Path(__file__).with_name("_worker.py").read_bytes(),
            )
            executable = Path(
                os.environ.get("QWENPAW_DESKTOP_PY_RUNTIME") or sys.executable,
            ).resolve()
            if getattr(sys, "frozen", False) and not os.environ.get(
                "QWENPAW_DESKTOP_PY_RUNTIME",
            ):
                raise RuntimeError(f"Desktop CPython runtime is unavailable")
            command = [str(executable), "-I", "-S", "-u", str(worker)]
            config = SandboxConfig(
                mode=SandboxMode.SEATBELT,
                workspace_dir=directory,
                allow_read_all=False,
                mounts=[
                    MountSpec(str(executable.parent.parent)),
                    MountSpec(sys.base_prefix),
                    MountSpec(directory, writable=True),
                ],
                network_allow=[],
            )
            env = {
                key: os.environ[key]
                for key in ("SystemRoot", "WINDIR", "LANG", "LC_ALL")
                if key in os.environ
            }
            env["TMPDIR"] = env["TEMP"] = env["TMP"] = directory
            if sys.platform == "win32":
                await self._start_windows(command, config, env)
            else:
                command = self._isolated_command(command, config)
                self.process = await asyncio.create_subprocess_exec(
                    *command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=directory,
                    env=env,
                    start_new_session=True,
                    limit=MAX_MESSAGE_BYTES,
                )
                self.input = self.process.stdin
                self.output = self.process.stdout
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    @staticmethod
    def _isolated_command(command, config):
        # pylint: disable=protected-access
        directory = config.workspace_dir
        if sys.platform == "darwin":
            sandbox = MacOSSandbox(config)
            # Allow the initial Python exec, but no child processes.
            profile = sandbox._compile_seatbelt_profile().replace(
                "(allow process-fork)",
                "(deny process-fork)",
            )
            for path in ("/tmp", "/private/tmp"):
                profile = profile.replace(
                    f'(allow file-write*\n  (subpath "{path}"))',
                    "",
                )
            profile += (
                f'\n(allow file-read* (literal "/"))\n' f"(deny signal)\n"
            )
            command = ["sandbox-exec", "-p", profile, *command]
        elif sys.platform == "linux":
            config.mode = SandboxMode.BUBBLEWRAP
            sandbox = BubblewrapSandbox(config)
            arguments = sandbox._build_bwrap_args(
                shlex.join(command),
                directory,
            )
            for path in ("/etc", "/run", "/sys"):
                for index in range(len(arguments) - 2):
                    if arguments[index : index + 3] == [
                        "--ro-bind",
                        path,
                        path,
                    ]:
                        del arguments[index : index + 3]
                        break
            for path in ("/tmp", "/dev/shm"):
                for index in range(len(arguments) - 2):
                    if arguments[index : index + 3] == [
                        "--bind",
                        path,
                        path,
                    ]:
                        arguments[index : index + 3] = [
                            "--tmpfs",
                            path,
                        ]
                        break
            arguments.insert(arguments.index("--"), "--unshare-net")
            command = [sandbox._find_bwrap(), *arguments]
        else:
            raise RuntimeError(
                f"No Code Mode process isolation for {sys.platform}",
            )
        return command

    async def _start_windows(self, command, config, env) -> None:
        config.mode = SandboxMode.WINDOWS
        sandbox = WindowsAppContainerSandbox(config)
        self.stack.push_async_callback(sandbox.destroy)
        await self.stack.enter_async_context(sandbox)
        child_input, host_input = os.pipe()
        host_output, child_output = os.pipe()
        with (
            os.fdopen(child_input, "rb") as reader,
            os.fdopen(child_output, "w", encoding="utf-8") as writer,
        ):
            self.input = self.stack.enter_context(os.fdopen(host_input, "wb"))
            self.output = self.stack.enter_context(
                os.fdopen(host_output, "rb"),
            )
            self.process = sandbox.spawn_process(
                command,
                cwd=config.workspace_dir,
                env=env,
                log_handle=writer,
                stdin_handle=reader,
            )

    async def send(self, packet: dict) -> None:
        data = f"{json.dumps(packet, ensure_ascii=False)}\n".encode("utf-8")
        if len(data) > MAX_MESSAGE_BYTES:
            raise ValueError(f"Code message exceeds 16 MiB")
        async with self.send_lock:
            if sys.platform == "win32":
                await asyncio.to_thread(self.input.write, data)
                await asyncio.to_thread(self.input.flush)
            else:
                self.input.write(data)
                await self.input.drain()

    async def receive(self) -> dict:
        if sys.platform == "win32":
            line = await asyncio.to_thread(
                self.output.readline,
                MAX_MESSAGE_BYTES + 1,
            )
        else:
            line = await self.output.readline()
        if not line:
            raise RuntimeError(f"CPython worker exited before completion")
        if len(line) > MAX_MESSAGE_BYTES:
            raise ValueError(f"Code message exceeds 16 MiB")
        try:
            return json.loads(line)
        except ValueError as exc:
            diagnostic = line.decode("utf-8", errors="replace")[:2048]
            raise RuntimeError(f"CPython worker failed: {diagnostic}") from exc

    async def watch(self) -> None:
        """Enforce CPU/RSS ceilings with a parent-side process watchdog."""
        while True:
            await asyncio.sleep(0.1)
            try:
                process = psutil.Process(self.process.pid)
                processes = [process, *process.children(recursive=True)]
                memory = sum(p.memory_info().rss for p in processes)
                cpu = sum(sum(p.cpu_times()[:2]) for p in processes)
                if memory > 256 * 1024 * 1024 or cpu > 10:
                    raise RuntimeError(f"Code exceeded its memory/CPU limit")
            except psutil.NoSuchProcess:
                return

    async def __aexit__(self, *_args):
        try:
            if self.process is not None:
                if sys.platform == "win32":
                    self.process.kill()
                    await asyncio.to_thread(self.process.wait, 5)
                else:
                    if self.process.returncode is None:
                        try:
                            if sys.platform == "darwin":
                                # Fork is denied, so this worker has no tree.
                                self.process.kill()
                            else:
                                os.killpg(self.process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    await self.process.wait()
        finally:
            await self.stack.aclose()
