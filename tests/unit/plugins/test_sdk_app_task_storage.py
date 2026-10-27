# -*- coding: utf-8 -*-
"""Real HTTP task persistence must not block unrelated async work."""

import asyncio
import os
import threading
import time
from pathlib import Path

import pytest

from .sdk_author_fixture import make_plugin

from .timing import WAIT_TIMEOUT, wait_for_thread_progress

pytestmark = pytest.mark.p1

SOURCE = """
import asyncio
from pathlib import Path
from qwenpaw.plugins.apps import PawApp
from qwenpaw.plugins.commands import CommandSpec, CommandResult
from qwenpaw.plugins.messages import Message, ContentBlock
class Plugin:
    def register(self, context):
        self.calls = 0
        async def wait(call, args):
            self.calls += 1
            while not Path(context.config.get("release")).exists():
                await asyncio.sleep(0.005)
            return CommandResult("reply", Message("assistant", (
                ContentBlock(text="finished"),
            )))
        app = PawApp(app_id="task-disk").enable_standard_capabilities()
        @app.route("/calls")
        async def calls(ctx, request):
            return {"calls": self.calls}
        context.register_command(CommandSpec("diskwait", wait))
        context.register_app(app)
plugin = Plugin()
"""


async def heartbeat(ticks):
    while True:
        ticks.append(time.monotonic())
        await asyncio.sleep(0.005)


async def start(host, session="disk"):
    response = await host.request(
        "POST",
        "/api/task-disk/tasks",
        user_id="alice",
        json={"message": "/diskwait", "session_id": session},
    )
    assert response.status == 200
    return response.json()


async def terminal(host, path):
    async with asyncio.timeout(WAIT_TIMEOUT):
        while True:
            response = await host.request("GET", path, user_id="alice")
            assert response.status == 200
            if response.json()["status"] != "running":
                return response.json()
            await asyncio.sleep(0.005)


@pytest.mark.parametrize("phase", ["start", "end", "retry", "read", "recover"])
async def test_task_storage_real_io_keeps_http_loop_responsive(
    tmp_path,
    monkeypatch,
    phase,
):
    from qwenpaw.plugins.testing import PluginTestHost

    release = tmp_path / "release"
    package = make_plugin(tmp_path, SOURCE, ["apps", "commands", "config"])
    async with PluginTestHost(tmp_path / "host") as host:
        context = await host.load(package, config={"release": str(release)})
        ticks, observations, writes = [], [], []
        local, armed = threading.local(), False
        write, fsync, read = (
            context.storage.write_json,
            os.fsync,
            Path.read_bytes,
        )

        def delay():
            before = len(ticks)
            wait_for_thread_progress(lambda: len(ticks) > before)
            observations.append(
                (threading.current_thread().name, len(ticks) - before),
            )

        def capture_write(key, value, *args, **kwargs):
            selected = str(key).startswith("sdk-task-status/")
            if selected:
                writes.append((key, value))
                if phase == "retry" and value["status"] == "completed":
                    raise OSError("task-terminal-first-write-failure")
            local.target = (
                selected
                and armed
                and value.get("status")
                == {
                    "start": "running",
                    "end": "completed",
                    "retry": "failed",
                    "recover": "interrupted",
                }.get(phase)
            )
            try:
                return write(key, value, *args, **kwargs)
            finally:
                local.target = False

        def slow_fsync(fd):
            if getattr(local, "target", False):
                delay()
            return fsync(fd)

        def slow_read(path):
            if phase == "read" and armed and "sdk-task-status" in path.parts:
                delay()
            return read(path)

        heart = asyncio.create_task(heartbeat(ticks))
        try:
            monkeypatch.setattr(context.storage, "write_json", capture_write)
            monkeypatch.setattr(os, "fsync", slow_fsync)
            monkeypatch.setattr(Path, "read_bytes", slow_read)
            await asyncio.sleep(0.01)
            armed = phase == "start"
            current = await start(host)
            path = "/api/task-disk/tasks/" + current["run_id"]
            armed = phase in {"end", "retry"}
            release.touch()
            saved = await terminal(host, path)
            assert saved["status"] == (
                "failed" if phase == "retry" else "completed"
            )
            if phase == "retry":
                assert "task-terminal-first-write-failure" in saved["error"]
            if phase in {"read", "recover"}:
                if phase == "recover":
                    key = writes[0][0]
                    write(key, {**saved, "status": "running"})
                armed = True
                saved = (
                    await host.request("GET", path, user_id="alice")
                ).json()
                assert saved["status"] == (
                    "interrupted" if phase == "recover" else "completed"
                )
            assert observations and all(
                thread != "MainThread" and delta > 0
                for thread, delta in observations
            ), observations
        finally:
            release.touch()
            heart.cancel()
            await asyncio.gather(heart, return_exceptions=True)


class DiskGate:
    """Pause the real fsync only for one task-status transition."""

    def __init__(self, monkeypatch, storage, status):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.snapshots = []
        self.threads = []
        local = threading.local()
        write, fsync = storage.write_json, os.fsync

        def capture(key, value, *args, **kwargs):
            local.target = (
                str(key).startswith("sdk-task-status/")
                and value.get("status") == status
            )
            if local.target:
                self.snapshots.append(dict(value))
            try:
                return write(key, value, *args, **kwargs)
            finally:
                local.target = False

        def gated_fsync(fd):
            if not getattr(local, "target", False):
                return fsync(fd)
            self.threads.append(threading.current_thread().name)
            self.entered.set()
            assert self.release.wait(
                WAIT_TIMEOUT * 2,
            ), "Test must release real fsync"
            result = fsync(fd)
            self.finished.set()
            return result

        monkeypatch.setattr(storage, "write_json", capture)
        monkeypatch.setattr(os, "fsync", gated_fsync)

    async def wait(self):
        async with asyncio.timeout(WAIT_TIMEOUT):
            while not self.entered.is_set():
                await asyncio.sleep(0.005)


async def test_initial_save_serializes_duplicate_start_and_recovery_read(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins.testing import PluginTestHost

    release = tmp_path / "release"
    package = make_plugin(tmp_path, SOURCE, ["apps", "commands", "config"])
    async with PluginTestHost(tmp_path / "host") as host:
        context = await host.load(package, config={"release": str(release)})
        gate = DiskGate(monkeypatch, context.storage, "running")
        first = asyncio.create_task(start(host))
        requests = [first]
        try:
            await gate.wait()
            path = "/api/task-disk/tasks/" + gate.snapshots[0]["run_id"]
            second = asyncio.create_task(start(host))
            reading = asyncio.create_task(
                host.request("GET", path, user_id="alice"),
            )
            requests.extend((second, reading))
            await asyncio.sleep(0.05)
            assert (
                await host.request("GET", "/api/task-disk/calls")
            ).json() == {"calls": 0}
            # An unfinished initial write must neither start author work nor
            # be mistaken for an abandoned run by a concurrent status read.
            assert not first.done() and not second.done()
            gate.release.set()
            first_result, second_result, read_result = await asyncio.gather(
                *requests,
            )
            assert first_result["run_id"] == second_result["run_id"]
            assert (
                read_result.status == 200
                and read_result.json()["status"] == "running"
            )
            async with asyncio.timeout(WAIT_TIMEOUT):
                while (
                    await host.request("GET", "/api/task-disk/calls")
                ).json()["calls"] < 1:
                    await asyncio.sleep(0.005)
            await asyncio.sleep(0.05)
            assert (
                await host.request("GET", "/api/task-disk/calls")
            ).json() == {"calls": 1}
            assert len(gate.snapshots) == 1
            release.touch()
            assert (await terminal(host, path))["status"] == "completed"
        finally:
            gate.release.set()
            release.touch()
            await asyncio.gather(*requests, return_exceptions=True)


@pytest.mark.parametrize("phase", ["running", "completed"])
async def test_task_disk_write_retains_owner_through_cancel_and_reload(
    tmp_path,
    monkeypatch,
    phase,
):
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.testing import PluginTestHost

    source = SOURCE.replace(
        "        context.register_app(app)",
        """        @app.route("/stop", methods=("POST",))
        async def stop(ctx, request):
            result = await ctx.cancel_task(
                request.json()["run_id"], timeout=0.02,
            )
            return {"stopped": result.stopped, "timed_out": result.timed_out}
        context.register_app(app)""",
    )
    release = tmp_path / "release"
    package = make_plugin(tmp_path, source, ["apps", "commands", "config"])
    async with PluginTestHost(tmp_path / "host") as host:
        context = await host.load(package, config={"release": str(release)})
        gate = DiskGate(monkeypatch, context.storage, phase)
        starting = asyncio.create_task(start(host))
        try:
            if phase == "completed":
                current = await starting
                release.touch()
            await gate.wait()
            if phase == "running":
                assert (
                    await host.request("GET", "/api/task-disk/calls")
                ).json() == {"calls": 0}
                starting.cancel()
                await asyncio.sleep(0.02)
                starting.cancel()
            else:
                for _ in range(2):
                    stopped = await host.request(
                        "POST",
                        "/api/task-disk/stop",
                        json={"run_id": current["run_id"]},
                        user_id="alice",
                    )
                    assert stopped.status == 200
                    assert stopped.json() == {
                        "stopped": False,
                        "timed_out": True,
                    }
            with pytest.raises(PluginBusyError):
                await host.reload("extension-contract", interrupt_tasks=True)
            assert not gate.finished.is_set()
            assert (
                host.resource_snapshot("extension-contract")["active_calls"]
                > 0
            )
            gate.release.set()
            assert await asyncio.to_thread(gate.finished.wait, WAIT_TIMEOUT)
            await asyncio.gather(starting, return_exceptions=True)
            assert all(name != "MainThread" for name in gate.threads)
            assert (
                await host.reload("extension-contract", interrupt_tasks=True)
            ).ok
            if phase == "completed":
                saved = await terminal(
                    host,
                    "/api/task-disk/tasks/" + current["run_id"],
                )
                assert saved["status"] in {"completed", "cancelled"}
                assert saved["result"] == "finished"
            host.assert_quiescent("extension-contract")
        finally:
            gate.release.set()
            release.touch()
            await asyncio.gather(starting, return_exceptions=True)


async def test_terminal_persistence_blocks_stale_reads_until_atomic_commit(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins.testing import PluginTestHost

    release = tmp_path / "release"
    package = make_plugin(tmp_path, SOURCE, ["apps", "commands", "config"])
    async with PluginTestHost(tmp_path / "host") as host:
        context = await host.load(package, config={"release": str(release)})
        gate = DiskGate(monkeypatch, context.storage, "completed")
        current = await start(host)
        path = "/api/task-disk/tasks/" + current["run_id"]
        reads = []
        try:
            release.touch()
            await gate.wait()
            reads = [
                asyncio.create_task(host.request("GET", path, user_id="alice"))
                for _ in range(5)
            ]
            await asyncio.sleep(0.03)
            assert all(not reading.done() for reading in reads)
            gate.release.set()
            responses = await asyncio.gather(*reads)
            assert all(
                response.json()["status"] == "completed"
                for response in responses
            )
            assert (await host.reload("extension-contract")).ok
            assert (await terminal(host, path))["status"] == "completed"
        finally:
            gate.release.set()
            release.touch()
            await asyncio.gather(*reads, return_exceptions=True)


async def test_failed_terminal_retry_keeps_diagnostic_until_restart(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins.testing import PluginTestHost

    release = tmp_path / "release"
    package = make_plugin(tmp_path, SOURCE, ["apps", "commands", "config"])
    async with PluginTestHost(tmp_path / "host") as host:
        context = await host.load(package, config={"release": str(release)})
        write = context.storage.write_json
        failures = []

        def broken_write(key, value, *args, **kwargs):
            if (
                str(key).startswith("sdk-task-status/")
                and value["status"] != "running"
            ):
                failures.append(value["status"])
                raise OSError("disk-offline-for-task-status")
            return write(key, value, *args, **kwargs)

        monkeypatch.setattr(context.storage, "write_json", broken_write)
        current = await start(host)
        path = "/api/task-disk/tasks/" + current["run_id"]
        release.touch()
        failed = await terminal(host, path)
        assert failures == ["completed", "failed"]
        assert failed["status"] == "failed"
        assert "disk-offline-for-task-status" in failed["error"]
        # A later read must retain the diagnostic instead of replacing it
        # with the stale running snapshot still on disk.
        assert (
            await host.request("GET", path, user_id="alice")
        ).json() == failed
        host.assert_quiescent("extension-contract")
        monkeypatch.setattr(context.storage, "write_json", write)
        again = await start(host)
        assert again["run_id"] == current["run_id"]
        assert (await terminal(host, path))["status"] == "completed"
        assert (await host.request("GET", "/api/task-disk/calls")).json() == {
            "calls": 2,
        }
        assert (await host.reload("extension-contract")).ok
        assert (await terminal(host, path))["status"] == "completed"
