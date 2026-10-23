# -*- coding: utf-8 -*-
# pylint: disable=missing-function-docstring,redefined-outer-name
# pylint: disable=import-outside-toplevel,too-many-locals
"""Installed candidate acceptance with real SDKs and controlled network.

Run separately per channel with QWENPAW_B5_CHANNEL. B3/B4 own the reusable
runtime; only their external-boundary text is instrumented here.
"""

import asyncio
from dataclasses import replace
import importlib
import json
import os
from pathlib import Path
import sys

import pytest
import psutil

sys.path.insert(0, str(Path(__file__).parent))
CHANNEL = os.environ["QWENPAW_B5_CHANNEL"]
contracts = importlib.import_module(f"{CHANNEL}_process_suite")
runtime = contracts.runtime
proxy_api = contracts.proxy_api


def instrument(monkeypatch, *, fault=""):
    original = Path.read_text
    boundary = Path(__file__).with_name(f"{CHANNEL}_process_boundary.py")
    # Failure/delay occurs at the external SDK import boundary, before real
    # SDK imports and the production Driver; production has no test hooks.
    prefix = {
        "delay": "import time; time.sleep(0.35)\n",
        "failure": "raise ImportError('controlled SDK import failure')\n",
        "": "",
    }[fault]
    suffix = """\nimport sys
record("origins", files={name: module.__file__ for name, module in
       list(sys.modules.items()) if name in ORIGIN_NAMES})
""".replace(
        "ORIGIN_NAMES",
        repr(
            [
                f"{CHANNEL}.driver",
                f"{CHANNEL}.platform",
                f"{CHANNEL}.transport",
                f"{CHANNEL}.sdk",
                f"{CHANNEL}.handler",
            ],
        ),
    )

    def read(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        return prefix + value + suffix if path == boundary else value

    monkeypatch.setattr(Path, "read_text", read)


@pytest.mark.asyncio
async def test_installed_layout_receive_send_restart_stop(
    runtime,
    monkeypatch,
):
    from qwenpaw.channel_protocol.shared import SharedChannelDescriptor

    instrument(monkeypatch)
    rt = await runtime()
    installed = rt.spec.code_root
    package = installed / CHANNEL
    assert not installed.is_relative_to(contracts.ROOT / "plugins")
    for name in (
        "plugin.json",
        "channel.json",
        "requirements.txt",
        "README.md",
    ):
        assert (installed / name).is_file()
    for name in ("driver.py", "__init__.py"):
        assert (package / name).is_file()
    assert rt.spec.descriptor_path == installed / "channel.json"
    formal_manifest = json.loads((installed / "plugin.json").read_text())
    assert formal_manifest["entry"] == {"descriptor": "channel.json"}
    source_descriptor = json.loads(
        (
            contracts.ROOT / "plugins/channel" / CHANNEL / "channel.json"
        ).read_text(),
    )
    # Unmodified artifact static discovery; connected runs explicitly use an
    # external boundary module instead of the declared Driver entrypoint.
    parsed = SharedChannelDescriptor.from_mapping(source_descriptor)
    assert parsed.channel_key == CHANNEL
    assert source_descriptor["entrypoint"]["module"] == f"{CHANNEL}.driver"
    assert (
        json.loads((installed / "plugin.json").read_text())["publish"] is False
    )
    origins = rt.rows("origins")[0]["files"]
    assert f"{CHANNEL}.driver" in origins
    assert (
        f"{CHANNEL}.platform" in origins or f"{CHANNEL}.transport" in origins
    )
    assert all(Path(path).is_relative_to(package) for path in origins.values())
    assert rt.process.health_snapshot()["pid"] != os.getpid()
    rt.emit(contracts.message("installed-first"))
    await contracts.eventually(lambda: len(rt.queued) == 1)
    await rt.channel.consume_one(rt.queued.pop())
    assert len(rt.requests) == 1
    sent_kind = "create" if CHANNEL == "feishu" else "http"
    assert rt.rows(sent_kind)
    assert all(row["pid"] != os.getpid() for row in rt.rows(sent_kind))
    old_pid = rt.process.health_snapshot()["pid"]
    config_snapshot = dict(rt.spec.config)
    state_files = list((rt.work / "channel_state").glob("*.json"))
    assert state_files
    await contracts.restart(rt)
    assert rt.process.health_snapshot()["pid"] != old_pid
    assert not psutil.pid_exists(old_pid)
    rt.emit(contracts.message("installed-after-restart"))
    await contracts.eventually(lambda: len(rt.queued) == 1)
    await rt.channel.consume_one(rt.queued.pop())
    assert len(rt.requests) == 2
    saved_records = {
        path: json.loads(path.read_text())
        for path in (rt.work / "channel_state").glob("*.json")
    }
    assert saved_records
    final_pid = rt.process.health_snapshot()["pid"]
    await rt.channel.stop()
    assert rt.process.health_snapshot()["pid"] is None
    assert not psutil.pid_exists(final_pid)
    assert dict(rt.spec.config) == config_snapshot
    assert all(path.exists() for path in state_files)
    assert {
        path: json.loads(path.read_text()) for path in saved_records
    } == saved_records
    assert not any(
        name == p or name.startswith(p + ".")
        for name in sys.modules
        for p in contracts.FORBIDDEN
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["delay", "failure"])
async def test_sdk_import_does_not_block_host(runtime, monkeypatch, fault):
    from qwenpaw.app.channels.process_supervisor import (
        ChannelProcess,
        ChannelProcessError,
    )

    observed = []
    start = ChannelProcess.start

    async def tracked_start(process, spec):
        observed.append(process)
        return await start(process, spec)

    monkeypatch.setattr(ChannelProcess, "start", tracked_start)
    instrument(monkeypatch, fault=fault)
    loop = asyncio.get_running_loop()
    errors = []
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: errors.append(context))
    ticks = []
    running = True

    async def heartbeat():
        while running:
            ticks.append(asyncio.get_running_loop().time())
            await asyncio.sleep(0.01)

    task = asyncio.create_task(heartbeat())
    try:
        if fault == "failure":
            with pytest.raises(ChannelProcessError) as caught:
                await runtime()
            assert str(caught.value) == "ENTRYPOINT_IMPORT_FAILED"
            assert observed[0].health_snapshot()["state"] == "failed"
            assert observed[0].health_snapshot()["last_error"]
            pid = observed[0].health_snapshot()["pid"]
            await observed[0].stop()
            assert observed[0].health_snapshot()["pid"] is None
            assert pid is None or not psutil.pid_exists(pid)
        else:
            rt = await runtime()
            assert len(ticks) >= 20
            assert max(b - a for a, b in zip(ticks, ticks[1:])) < 0.2
            await rt.channel.stop()
            assert rt.process.health_snapshot()["pid"] is None
    finally:
        running = False
        await task
        await asyncio.sleep(0.05)
        loop.set_exception_handler(old_handler)
    assert not errors, errors
    assert len(ticks) >= 2


@pytest.mark.asyncio
async def test_missing_installed_driver_has_no_source_fallback(
    runtime,
    monkeypatch,
):
    instrument(monkeypatch)
    rt = await runtime()
    await rt.channel.stop()
    # Restore the exact original artifact descriptor: no wrapper entrypoint.
    descriptor = contracts.ROOT / "plugins/channel" / CHANNEL / "channel.json"
    rt.spec.descriptor_path.write_bytes(descriptor.read_bytes())
    (rt.spec.code_root / CHANNEL / "driver.py").unlink()
    rt.spec = replace(
        rt.spec,
        source_revision=contracts.digest(rt.spec.code_root),
    )
    from qwenpaw.app.channels.process_supervisor import ChannelProcessError

    loop = asyncio.get_running_loop()
    errors = []
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: errors.append(context))

    with pytest.raises(ChannelProcessError) as caught:
        await rt.process.start(rt.spec)
    assert str(caught.value) == "ENTRYPOINT_OUTSIDE_CODE_ROOT"
    health = rt.process.health_snapshot()
    assert health["state"] == "failed"
    assert health["last_error"]
    await rt.process.stop()
    assert rt.process.health_snapshot()["pid"] is None
    await asyncio.sleep(0.05)
    loop.set_exception_handler(old_handler)
    assert not errors, errors


@pytest.mark.asyncio
async def test_runtime_crash_is_unknown_and_child_reaped(runtime, monkeypatch):
    instrument(monkeypatch)
    rt = await runtime()
    child_pid = rt.process.health_snapshot()["pid"]
    (rt.work / "send-mode").write_text(
        "commit-exit" if CHANNEL == "feishu" else "webhook-exit",
    )
    from qwenpaw.app.channels.process_supervisor import ChannelCallUnknown

    with pytest.raises(ChannelCallUnknown):
        await rt.channel.send(
            "ou_alice" if CHANNEL == "feishu" else contracts.WEBHOOK,
            "crash acceptance",
        )
    assert rt.process.health_snapshot()["unknown_outcomes"]
    await contracts.eventually(
        lambda: rt.process.health_snapshot()["state"] == "failed",
    )
    assert rt.process.health_snapshot()["last_error"] == "WORKER_EXITED"
    assert not psutil.pid_exists(child_pid)
    await rt.channel.stop()
    assert rt.process.health_snapshot()["pid"] is None
