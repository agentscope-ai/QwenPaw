# -*- coding: utf-8 -*-
"""Real shell resource regressions for Windows, macOS and Linux.

The existing nightly unit-test matrix runs these on all three systems.
Only shell selection is configured; process sampling and killing are real.
"""

import asyncio
import ctypes
import ctypes.wintypes
import io
import os
import shlex
import subprocess
import sys
import threading
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import psutil
import pytest
from agentscope.message import ToolResultState

from qwenpaw.agents.tools import shell
from qwenpaw.agents.tools.shell import execute_shell_command
from qwenpaw.sandbox import SandboxConfig, SandboxMode
from qwenpaw.sandbox import windows_appcontainer_sandbox as appcontainer
from qwenpaw.sandbox import windows_unelevated_sandbox as windows_readers
from qwenpaw.utils.shell_resources import (
    SHELL_GUARD,
    ShellGuard,
    watch_shell_process_async,
)


@pytest.mark.parametrize("sandboxed", [False, True])
@pytest.mark.parametrize("resource", ["memory", "output"])
async def test_guard_terminates_command_tree(
    monkeypatch,
    tmp_path,
    sandboxed,
    resource,
):
    """Kill a real tree, preserve diagnostics, and bound captured output."""
    monkeypatch.setenv(
        "QWENPAW_SHELL_MEMORY_LIMIT_MB",
        "96" if resource == "memory" else "512",
    )
    executable = "cmd.exe" if sys.platform == "win32" else "/bin/sh"
    script = tmp_path / "resource probe.py"
    script.write_text(
        "import os, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "if len(sys.argv) == 1:\n"
        "    children = [subprocess.Popen([sys.executable, __file__,\n"
        "                'child']) for _ in range(2)]\n"
        "    pids = [os.getpid()] + [p.pid for p in children]\n"
        "    Path(__file__).with_suffix('.pids').write_text(\n"
        "        ','.join(str(pid) for pid in pids))\n"
        "    for child in children: child.wait()\n"
        "    sys.exit(1 if any(p.returncode for p in children) else 0)\n"
        "print('original stderr', file=sys.stderr, flush=True)\n"
        "time.sleep(0.1)\n"
        + (
            # Each child fits alone; their combined RSS exceeds 96 MiB.
            "data = bytearray(48 * 1024 * 1024)\n"
            "data[::4096] = b'x' * (len(data) // 4096)\n"
            if resource == "memory"
            else "for _ in range(256):\n"
            "    sys.stdout.buffer.write(b'x' * 65536)\n"
            "    sys.stdout.buffer.flush()\n"
        )
        + "time.sleep(5)\n",
        encoding="utf-8",
    )
    argv = [sys.executable, str(script)]
    command = (
        subprocess.list2cmdline(argv)
        if sys.platform == "win32"
        else shlex.join(argv)
    )
    config = (
        SandboxConfig(mode=SandboxMode.NONE, workspace_dir=str(tmp_path))
        if sandboxed
        else None
    )
    with patch(
        "qwenpaw.agents.tools.shell.get_current_shell_command_executable",
        return_value=executable,
    ):
        result = await execute_shell_command(
            command,
            cwd=tmp_path,
            timeout=10,
            sandbox_config=config,
        )
    text = "\n".join(block.text for block in result.content)
    assert result.state == ToolResultState.ERROR
    assert f"Shell {resource} limit exceeded" in text
    assert "original stderr" in text
    assert "exit code" in text
    assert len(text) < 2 * 1024 * 1024
    processes = []
    for pid in script.with_suffix(".pids").read_text().split(","):
        try:
            processes.append(psutil.Process(int(pid)))
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(processes, timeout=3)
    for process in alive:
        try:
            assert process.status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            pass
    assert SHELL_GUARD.get() is None
    assert not any(
        thread.name == "qwenpaw-shell-guard"
        for thread in threading.enumerate()
    )


async def test_disabled_guard_does_not_probe_resources(monkeypatch):
    """Keep the default path free of process scans and memory probes."""
    monkeypatch.delenv("QWENPAW_SHELL_MEMORY_LIMIT_MB", raising=False)
    with (
        patch(
            "qwenpaw.utils.shell_resources.psutil.virtual_memory",
            side_effect=AssertionError("Unexpected memory probe"),
        ),
        patch(
            "qwenpaw.utils.shell_resources.psutil.Process",
            side_effect=AssertionError("Unexpected process probe"),
        ),
        patch(
            "qwenpaw.agents.tools.shell._execute_posix_host",
            new=AsyncMock(return_value=(0, "unchanged", "")),
        ),
        patch(
            "qwenpaw.agents.tools.shell._execute_windows_host",
            new=AsyncMock(return_value=(0, "unchanged", "")),
        ),
    ):
        result = await execute_shell_command("echo unchanged")
    assert result.content[0].text == "unchanged"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX background jobs")
@pytest.mark.parametrize("limit", ["0", "512"])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_background_process_lifecycle(
    monkeypatch,
    tmp_path,
    limit,
    cancelled,
):
    """Preserve successful background jobs; clean observed jobs on cancel."""
    monkeypatch.setenv("QWENPAW_SHELL_MEMORY_LIMIT_MB", limit)
    script = tmp_path / "background.py"
    script.write_text(
        "import subprocess, sys, time\n"
        "from pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c',\n"
        "    'import time; time.sleep(30)'],\n"
        "    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,\n"
        "    stderr=subprocess.DEVNULL, start_new_session=True)\n"
        "Path(__file__).with_suffix('.pid').write_text(str(child.pid))\n"
        "print(child.pid, flush=True)\n"
        + ("time.sleep(30)\n" if cancelled else "time.sleep(0.75)\n"),
        encoding="utf-8",
    )
    with patch(
        "qwenpaw.agents.tools.shell.get_current_shell_command_executable",
        return_value="/bin/sh",
    ):
        task = asyncio.create_task(
            execute_shell_command(
                shlex.join([sys.executable, str(script)]),
                cwd=tmp_path,
            ),
        )
        pid_file = script.with_suffix(".pid")
        for _ in range(100):
            if pid_file.exists() and pid_file.read_text():
                break
            await asyncio.sleep(0.05)
        child = psutil.Process(int(pid_file.read_text()))
        try:
            if cancelled:
                await asyncio.sleep(0.5)
                task.cancel()
            result = await task
            if cancelled and limit != "0":
                child.wait(timeout=3)
            else:
                if not cancelled:
                    assert result.state == ToolResultState.SUCCESS
                assert child.is_running()
                assert child.status() != psutil.STATUS_ZOMBIE
        finally:
            if child.is_running():
                child.kill()
                child.wait(timeout=3)


async def test_unavailable_monitoring_runs_without_protection(monkeypatch):
    """A restricted host still executes commands and reports degradation."""
    monkeypatch.setenv("QWENPAW_SHELL_MEMORY_LIMIT_MB", "512")
    with (
        patch.object(
            psutil,
            "virtual_memory",
            side_effect=psutil.AccessDenied,
        ),
        patch(
            "qwenpaw.agents.tools.shell._execute_posix_host",
            new=AsyncMock(return_value=(0, "executed", "")),
        ) as posix,
        patch(
            "qwenpaw.agents.tools.shell._execute_windows_host",
            new=AsyncMock(return_value=(0, "executed", "")),
        ) as windows,
    ):
        result = await execute_shell_command("echo executed")
    assert result.state == ToolResultState.SUCCESS
    assert result.content[0].text == "executed"
    assert "continuing without memory protection" in result.content[1].text
    assert posix.await_count + windows.await_count == 1
    assert SHELL_GUARD.get() is None


async def test_monitoring_permission_loss_keeps_command_running(
    monkeypatch,
    tmp_path,
):
    """Losing access after startup must not kill a healthy command."""
    monkeypatch.setenv("QWENPAW_SHELL_MEMORY_LIMIT_MB", "512")
    original_children = psutil.Process.children

    def children(process, *args, **kwargs):
        if process.pid != os.getpid():
            raise psutil.AccessDenied(process.pid)
        return original_children(process, *args, **kwargs)

    monkeypatch.setattr(psutil.Process, "children", children)
    argv = [
        sys.executable,
        "-c",
        "import time; time.sleep(0.75); print('continued')",
    ]
    command = (
        subprocess.list2cmdline(argv)
        if sys.platform == "win32"
        else shlex.join(argv)
    )
    with patch(
        "qwenpaw.agents.tools.shell.get_current_shell_command_executable",
        return_value="cmd.exe" if sys.platform == "win32" else "/bin/sh",
    ):
        result = await execute_shell_command(command, cwd=tmp_path)
    assert result.state == ToolResultState.SUCCESS
    assert result.content[0].text == "continued"
    assert "continuing without memory protection" in result.content[1].text


async def test_guard_initialization_and_registration_run_off_loop(monkeypatch):
    """System queries and watchdog startup must not block the event loop."""
    monkeypatch.setenv("QWENPAW_SHELL_MEMORY_LIMIT_MB", "512")
    loop_thread = threading.get_ident()
    original_memory = psutil.virtual_memory
    original_watch = ShellGuard.watch

    def memory():
        assert threading.get_ident() != loop_thread
        return original_memory()

    def watch(guard, pid, output_size):
        assert threading.get_ident() != loop_thread
        return original_watch(guard, pid, output_size)

    monkeypatch.setattr(psutil, "virtual_memory", memory)
    monkeypatch.setattr(ShellGuard, "watch", watch)
    guard = await ShellGuard.from_environment(10485760)
    child = await asyncio.to_thread(
        subprocess.Popen,
        [sys.executable, "-c", "import time; time.sleep(30)"],
    )
    token = SHELL_GUARD.set(guard)
    try:
        await watch_shell_process_async(child.pid)
    finally:
        SHELL_GUARD.reset(token)
        await asyncio.to_thread(guard.close, True)
        await asyncio.to_thread(child.wait, 3)


@pytest.mark.parametrize("backend", ["restricted", "appcontainer"])
async def test_windows_reader_threads_share_output_guard(monkeypatch, backend):
    """Exercise real reader/thread code with only the Win32 boundary faked."""
    guard = ShellGuard(1024**3, 3 * 1024**2)
    size = 2 * 1024**2
    remaining = {101: size, 102: size}
    threads = {}
    barrier = threading.Barrier(2, timeout=3)
    kernel32 = MagicMock()
    kernel32.WaitForSingleObject.return_value = 0

    def read_file(handle, buffer, capacity, count_pointer, _overlapped):
        assert SHELL_GUARD.get() is guard
        if remaining[handle] == size:
            threads[handle] = threading.get_ident()
            barrier.wait()
        count = min(capacity, remaining[handle])
        ctypes.cast(
            count_pointer,
            ctypes.POINTER(ctypes.wintypes.DWORD),
        ).contents.value = count
        if count:
            ctypes.memmove(buffer, b"x" * count, count)
            remaining[handle] -= count
        return bool(count)

    kernel32.ReadFile.side_effect = read_file
    module = windows_readers if backend == "restricted" else appcontainer
    monkeypatch.setattr(module, "_get_kernel32", lambda: kernel32)
    token = SHELL_GUARD.set(guard)
    try:
        if backend == "restricted":
            result = await asyncio.to_thread(
                module._wait_and_read_process,
                100,
                101,
                102,
                5,
            )
        else:
            result = await module._wait_and_read_process(100, 101, 102, 5)
    finally:
        SHELL_GUARD.reset(token)
    _, stdout, stderr, timed_out = result
    assert not timed_out
    assert len(set(threads.values())) == 2
    for stream in (stdout, stderr):
        assert stream == "x" * 1024**2 + "\n[output truncated]"
    assert "Shell output limit exceeded" in guard.failure


def test_windows_stops_guard_before_closing_output_readers():
    """The watchdog must release reader callbacks before handle cleanup."""
    readers = [tempfile.TemporaryFile(), tempfile.TemporaryFile()]
    writers = [io.BytesIO(), io.BytesIO()]
    guard = MagicMock(spec=ShellGuard)

    def stop_guard():
        assert all(not reader.closed for reader in readers)

    guard.close.side_effect = stop_guard
    process = MagicMock(pid=123, returncode=0)
    process.wait.return_value = 0
    with (
        patch.object(sys, "platform", "win32"),
        patch.object(
            shell,
            "_open_windows_temp_output",
            side_effect=zip(
                writers,
                readers,
            ),
        ),
        patch.object(shell.subprocess, "Popen", return_value=process),
        patch.object(shell, "_windows_shell_creationflags", return_value=0),
        patch.object(shell, "_create_job_object_win32", return_value=None),
        patch.object(
            shell,
            "_get_process_handle_from_popen",
            return_value=None,
        ),
        patch.object(shell, "watch_shell_process", return_value=guard),
    ):
        result = shell._execute_subprocess_sync("echo ok", None, 1, None, None)
    assert result[0] == 0
    guard.close.assert_called_once()
    assert all(reader.closed for reader in readers)
