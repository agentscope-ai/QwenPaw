# -*- coding: utf-8 -*-
"""Real shell resource regressions for Windows, macOS and Linux.

The existing nightly unit-test matrix runs these on all three systems.
Only shell selection is configured; process sampling and killing are real.
"""

import shlex
import subprocess
import sys
import threading
from unittest.mock import AsyncMock, patch

import psutil
import pytest
from agentscope.message import ToolResultState

from qwenpaw.agents.tools.shell import execute_shell_command
from qwenpaw.sandbox import SandboxConfig, SandboxMode
from qwenpaw.utils.shell_resources import SHELL_GUARD


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
