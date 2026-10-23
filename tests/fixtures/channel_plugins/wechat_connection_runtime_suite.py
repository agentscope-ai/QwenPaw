"""Trusted connection budget with actual generic worker and offline SDK gate."""

import asyncio
import json
import sys
import textwrap

import psutil
import pytest

from qwenpaw.plugins.channel_adapter import describe_channel
from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.execution.process import ProcessError

from extension_sample import ROOT, sample_source


def gated_proxy(tmp_path, *, connection_timeout, import_gate=False):
    key = "independent_connection_owner"
    source = sample_source(tmp_path / "incoming", key)
    gate = tmp_path / "sdk-release"
    marker = tmp_path / "sdk-started"
    sdk = source / key / "sdk.py"
    sdk.write_text(
        sdk.read_text()
        + textwrap.dedent(f"""
            import asyncio
            import time
            from pathlib import Path
            GATE = Path({str(gate)!r})
            MARKER = Path({str(marker)!r})
            async def connect():
                MARKER.write_text(str(PID))
                while not GATE.exists():
                    await asyncio.sleep(0.01)
            """)
        + (
            "\nMARKER.write_text(str(PID))\n"
            "while not GATE.exists():\n    time.sleep(0.01)\n"
            if import_gate
            else ""
        )
    )
    driver = source / key / "driver.py"
    driver.write_text(
        driver.read_text().replace(
            "    async def start(self, config):\n",
            "    async def start(self, config):\n"
            "        from .sdk import connect\n"
            "        await connect()\n",
            1,
        )
    )
    manifest = PluginManifest.from_dict(
        json.loads((source / "plugin.json").read_text())
    )
    proxy = describe_channel(source, manifest).create_proxy(
        None,
        {"enabled": True},
        python_executable=sys.executable,
        support_root=ROOT / "src",
        instance_id="connection-workspace",
        generation=1,
        qwenpaw_version="2.2.2b4",
        workspace_dir=tmp_path / "workspace",
        startup_timeout=1,
        shutdown_timeout=1,
        connection_timeout=connection_timeout,
    )
    return proxy, gate, marker


async def marker_pid(marker):
    async with asyncio.timeout(3):
        while not marker.exists():
            await asyncio.sleep(0.01)
    return int(marker.read_text())


@pytest.mark.asyncio
async def test_late_sdk_connection_exceeds_startup_budget_but_connects(
    tmp_path,
):
    proxy, gate, marker = gated_proxy(tmp_path, connection_timeout=4)
    task = asyncio.create_task(proxy.start())
    try:
        pid = await marker_pid(marker)
        await asyncio.sleep(1.1)
        snapshot = proxy.channel_process.health_snapshot()
        assert snapshot["state"] == "ready"
        assert snapshot["platform_state"] == "connecting"
        assert not task.done() and psutil.pid_exists(pid)
        gate.touch()
        await task
        assert proxy.channel_process.health_snapshot()["platform_state"] == (
            "connected"
        )
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        receipt = await proxy.stop()
        assert receipt.exited
    assert not psutil.pid_exists(pid)


@pytest.mark.asyncio
async def test_none_connection_budget_retains_short_legacy_timeout(tmp_path):
    proxy, _gate, marker = gated_proxy(tmp_path, connection_timeout=None)
    try:
        with pytest.raises(TimeoutError):
            await proxy.start()
        pid = await marker_pid(marker)
        snapshot = proxy.channel_process.health_snapshot()
        assert snapshot["state"] == "ready"
        assert snapshot["platform_state"] == "connecting"
    finally:
        receipt = await proxy.stop()
        assert receipt.exited
    assert not psutil.pid_exists(pid)


@pytest.mark.asyncio
async def test_long_connection_budget_does_not_extend_import_startup(tmp_path):
    proxy, _gate, marker = gated_proxy(
        tmp_path, connection_timeout=4, import_gate=True
    )
    started = asyncio.get_running_loop().time()
    task = asyncio.create_task(proxy.start())
    try:
        pid = await marker_pid(marker)
        with pytest.raises(ProcessError, match="^STARTUP_TIMEOUT$"):
            await task
        assert asyncio.get_running_loop().time() - started < 2
        assert proxy.channel_process.health_snapshot()["state"] != "ready"
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        receipt = await proxy.stop()
        assert receipt.exited
    assert not psutil.pid_exists(pid)


@pytest.mark.asyncio
async def test_cancel_waiting_connection_stops_real_child_promptly(tmp_path):
    proxy, _gate, marker = gated_proxy(tmp_path, connection_timeout=4)
    task = asyncio.create_task(proxy.start())
    try:
        pid = await marker_pid(marker)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with asyncio.timeout(2):
            receipt = await proxy.stop()
        assert receipt.exited
        assert not psutil.pid_exists(pid)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await proxy.stop()
