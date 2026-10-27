# -*- coding: utf-8 -*-
"""Fresh CPython workers backed by shared sandbox process sessions."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from contextlib import AsyncExitStack, ExitStack
from dataclasses import replace
from pathlib import Path

import psutil

from ...sandbox import MountSpec, SandboxConfig, SandboxMode
from ...sandbox.process import SandboxProcess
from ...utils.io_utils import run_sync_io

MAX_MESSAGE_BYTES = 16 * 1024 * 1024


class WorkerProcess:
    """Own the Python protocol and its bounded execution lifetime."""

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self.config = config
        self.stack = AsyncExitStack()
        self.files = ExitStack()
        self.stack.push_async_callback(run_sync_io, self.files.close)
        self.session = None
        self.send_lock = asyncio.Lock()

    def _prepare(self):
        directory = self.files.enter_context(
            tempfile.TemporaryDirectory(prefix=f"qwenpaw-code-"),
        )
        path = Path(directory).resolve()
        worker = path / f"worker.py"
        worker.write_bytes(
            Path(__file__).with_name(f"_worker.py").read_bytes(),
        )
        runtime = os.environ.get(f"QWENPAW_DESKTOP_PY_RUNTIME")
        if getattr(sys, f"frozen", False) and not runtime:
            raise RuntimeError(f"Desktop CPython runtime is unavailable")
        executable = Path(runtime or sys.executable).resolve()
        command = [str(executable), f"-I", f"-S", f"-u", str(worker)]
        config = self.config
        if config is None:
            config = SandboxConfig(
                mode=SandboxMode.NONE,
                workspace_dir=str(path),
                network_allow=[f"*"],
            )
        else:
            config = replace(
                config,
                mounts=[
                    *config.mounts,
                    MountSpec(str(executable.parent.parent)),
                    MountSpec(sys.base_prefix),
                    MountSpec(str(path), writable=True),
                ],
            )
        env = {
            key: os.environ[key]
            for key in (f"SystemRoot", f"WINDIR", f"LANG", f"LC_ALL")
            if key in os.environ
        }
        env[f"TMPDIR"] = env[f"TEMP"] = env[f"TMP"] = str(path)
        return SandboxProcess(
            config,
            command,
            cwd=str(path),
            env=env,
            limit=MAX_MESSAGE_BYTES,
        )

    async def __aenter__(self):
        preparation = asyncio.create_task(run_sync_io(self._prepare))
        try:
            self.session = await asyncio.shield(preparation)
            await self.stack.enter_async_context(self.session)
        except BaseException:
            try:
                await preparation
            finally:
                await self.stack.aclose()
            raise
        return self

    async def send(self, packet: dict) -> None:
        data = await asyncio.to_thread(self._encode, packet)
        async with self.send_lock:
            await self.session.write(data)

    @staticmethod
    def _encode(packet):
        data = f"{json.dumps(packet, ensure_ascii=False)}\n".encode(f"utf-8")
        if len(data) > MAX_MESSAGE_BYTES:
            raise ValueError(f"Code message exceeds 16 MiB")
        return data

    async def receive(self) -> dict:
        line = await self.session.readline()
        if not line:
            raise RuntimeError(f"CPython worker exited before completion")
        if len(line) > MAX_MESSAGE_BYTES:
            raise ValueError(f"Code message exceeds 16 MiB")
        try:
            return await asyncio.to_thread(json.loads, line)
        except ValueError as exc:
            diagnostic = line.decode(f"utf-8", errors=f"replace")[:2048]
            raise RuntimeError(f"CPython worker failed: {diagnostic}") from exc

    def _check_resources(self) -> bool:
        try:
            process = psutil.Process(self.session.process.pid)
            processes = [process, *process.children(recursive=True)]
            memory = 0
            cpu = 0.0
            for child in processes:
                try:
                    memory += child.memory_info().rss
                    cpu += sum(child.cpu_times()[:2])
                except psutil.NoSuchProcess:
                    continue
            if memory > 256 * 1024 * 1024:
                raise RuntimeError(f"Code exceeded its 256 MiB memory limit")
            if cpu > 10:
                raise RuntimeError(f"Code exceeded its 10 CPU-second limit")
            return True
        except psutil.NoSuchProcess:
            return False

    async def watch(self) -> None:
        """Sample process trees off the event loop, including exit races."""
        while True:
            await asyncio.sleep(0.1)
            if not await asyncio.to_thread(self._check_resources):
                return

    async def __aexit__(self, *_args):
        await self.stack.aclose()
