# -*- coding: utf-8 -*-
"""Owned SDK resource cleanup through the public author test host."""

import asyncio
import json
import subprocess
import sys
import threading

import pytest


def make_plugin(tmp_path, body):
    root = tmp_path / "resource-plugin"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": "resource-contract",
                "version": "1.0.0",
                "entry": {"backend": "main.py"},
                "sdk": {"version": "1.0", "capabilities": ["resources"]},
            },
        ),
        encoding="utf-8",
    )
    (root / "main.py").write_text(body, encoding="utf-8")
    return root


async def test_partial_activation_failure_closes_created_resource(tmp_path):
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from pathlib import Path
class Plugin:
    def register(self, ctx):
        def activate(ctx):
            marker = Path(ctx.config.get("marker"))
            ctx.resources.defer(lambda: marker.write_text("closed"), "opened")
            marker.write_text("opened")
            raise RuntimeError("activation broke after allocation")
        ctx.on_activate(activate)
plugin = Plugin()
"""
    marker = tmp_path / "resource-state"
    async with PluginTestHost(tmp_path / "host") as host:
        with pytest.raises(RuntimeError, match="activation broke"):
            await host.load(
                make_plugin(tmp_path, source),
                config={"marker": str(marker)},
            )
        assert marker.read_text() == "closed"
        host.assert_quiescent("resource-contract")


async def test_close_failure_blocks_replacement_and_remains_retryable(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from pathlib import Path
class Plugin:
    def register(self, ctx):
        def activate(ctx):
            directory = Path(ctx.config.get("directory"))
            with (directory / "activations").open("a") as stream:
                stream.write("activated\\n")
            class Connection:
                async def close(self):
                    (directory / "close-attempted").touch()
                    if (directory / "blocked").exists():
                        raise RuntimeError("connection remains open")
            ctx.resources.connection(Connection())
        ctx.on_activate(activate)
plugin = Plugin()
"""
    blocked = tmp_path / "blocked"
    blocked.touch()
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(tmp_path, source),
            config={"directory": str(tmp_path)},
        )
        before = host.resource_snapshot("resource-contract")
        try:
            report = await host.reload("resource-contract")
            assert not report.ok and report.needs_restart
            assert (tmp_path / "activations").read_text() == "activated\n"
            assert (tmp_path / "close-attempted").exists()
            failed = host.resource_snapshot("resource-contract")
            assert failed["owner"] == before["owner"]
            assert failed[
                "resources"
            ], "Failed close must retain resource ownership"
            with pytest.raises(AssertionError):
                host.assert_quiescent("resource-contract")
        finally:
            blocked.unlink()
        report = await host.unload("resource-contract")
        assert report.clean and report.quiescent
        host.assert_quiescent("resource-contract")


async def test_child_scope_release_is_idempotent_and_instance_local(tmp_path):
    from qwenpaw.plugins.testing import PluginTestHost

    source = (
        "class Plugin:\n    def register(self, ctx):\n        "
        "pass\nplugin = Plugin()\n"
    )
    closed, scopes = [], []
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(make_plugin(tmp_path, source))
        for workspace, instance in [("one", "a"), ("one", "b"), ("two", "a")]:
            scope = ctx.resources.child(
                workspace_id=workspace,
                instance_id=instance,
            )
            scope.defer(lambda key=(workspace, instance): closed.append(key))
            scopes.append(scope)
        assert [
            (scope.owner.workspace_id, scope.owner.instance_id)
            for scope in scopes
        ] == [
            ("one", "a"),
            ("one", "b"),
            ("two", "a"),
        ]
        await scopes[0].close()
        await scopes[0].close()
        assert closed == [("one", "a")]
        assert not scopes[1].closed and not scopes[2].closed
        report = await host.unload("resource-contract")
        assert report.clean and report.quiescent
        assert closed == [("one", "a"), ("two", "a"), ("one", "b")]
        host.assert_quiescent("resource-contract")


async def test_registration_phase_cannot_start_background_work(tmp_path):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from pathlib import Path
class Plugin:
    def register(self, ctx):
        async def worker():
            Path(ctx.config.get("marker")).touch()
        ctx.resources.task(worker())
plugin = Plugin()
"""
    marker = tmp_path / "worker-started"
    async with PluginTestHost(tmp_path / "host") as host:
        with pytest.raises(SDKError):
            await host.load(
                make_plugin(tmp_path, source),
                config={"marker": str(marker)},
            )
        assert not marker.exists()
        host.assert_quiescent("resource-contract")


async def test_synchronous_cleanup_does_not_block_host_event_loop(tmp_path):
    from qwenpaw.plugins.testing import PluginTestHost

    source = (
        "class Plugin:\n    def register(self, ctx):\n        "
        "pass\nplugin = Plugin()\n"
    )
    release = threading.Event()
    timer = threading.Timer(0.3, release.set)
    try:
        async with PluginTestHost(tmp_path / "host") as host:
            ctx = await host.load(make_plugin(tmp_path, source))
            heartbeat = asyncio.Event()
            handle = ctx.resources.defer(
                lambda: release.wait(2),
                "blocking-close",
            )
            asyncio.get_running_loop().call_later(0.02, heartbeat.set)
            timer.start()
            await handle.close()
            assert (
                heartbeat.is_set()
            ), "Synchronous cleanup blocked unrelated host work"
            assert handle.closed
    finally:
        release.set()
        if timer.ident is not None:
            timer.join(timeout=1)


async def test_cancelling_close_waiter_retains_underlying_sync_cleanup(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = (
        "class Plugin:\n    def register(self, ctx):\n        "
        "pass\nplugin = Plugin()\n"
    )
    entered, release = threading.Event(), threading.Event()
    calls = []

    def close():
        calls.append("start")
        entered.set()
        release.wait(3)
        calls.append("end")

    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(make_plugin(tmp_path, source))
        handle = ctx.resources.defer(close, "sync-cleanup")
        closing = asyncio.create_task(handle.close())
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
            assert not handle.closed
            assert calls == ["start"]
            assert (
                "sync-cleanup"
                in host.resource_snapshot("resource-contract")["resources"]
            )
            with pytest.raises(AssertionError):
                host.assert_quiescent("resource-contract")
        finally:
            release.set()
            await handle.close()
        assert handle.closed and calls == ["start", "end"]


async def test_unstoppable_thread_prevents_successful_unload(tmp_path):
    from qwenpaw.plugins.testing import PluginTestHost

    source = (
        "class Plugin:\n    def register(self, ctx):\n        "
        "pass\nplugin = Plugin()\n"
    )
    stop, release = threading.Event(), threading.Event()
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(make_plugin(tmp_path, source))
        worker = ctx.resources.thread(
            lambda: release.wait(10),
            stop=stop,
            description="ignores-stop",
        )
        try:
            report = await asyncio.wait_for(
                host.unload("resource-contract"),
                8,
            )
            assert stop.is_set() and worker.is_alive()
            assert (
                not report.clean
                and not report.quiescent
                and report.needs_restart
            )
            assert (
                "ignores-stop"
                in host.resource_snapshot("resource-contract")["resources"]
            )
        finally:
            release.set()
            await asyncio.to_thread(worker.join, 2)
            assert not worker.is_alive()
        report = await host.unload("resource-contract")
        assert report.clean and report.quiescent


async def test_finished_managed_tasks_do_not_accumulate_live_resources(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = (
        "class Plugin:\n    def register(self, ctx):\n        "
        "pass\nplugin = Plugin()\n"
    )
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(make_plugin(tmp_path, source))
        for _ in range(100):
            await ctx.resources.task(
                asyncio.sleep(0),
                description="short-lived",
            )
        await asyncio.sleep(0)
        assert host.resource_snapshot("resource-contract")["resources"] == ()
        host.assert_quiescent("resource-contract")


async def test_owned_process_stops_without_touching_independent_process(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = (
        "class Plugin:\n    def register(self, ctx):\n        "
        "pass\nplugin = Plugin()\n"
    )
    command = [sys.executable, "-c", "import time; time.sleep(10)"]
    independent = subprocess.Popen(command)
    try:
        async with PluginTestHost(tmp_path / "host") as host:
            ctx = await host.load(make_plugin(tmp_path, source))
            owned = ctx.resources.process(command, description="owned-child")
            assert owned.poll() is None and independent.poll() is None
            report = await host.unload("resource-contract")
            assert report.clean and report.quiescent
            assert owned.poll() is not None
            assert independent.poll() is None
    finally:
        independent.terminate()
        independent.wait(timeout=2)


async def test_finished_background_failure_remains_diagnosable(tmp_path):
    from qwenpaw.plugins.testing import PluginTestHost

    source = (
        "class Plugin:\n    def register(self, ctx):\n        "
        "pass\nplugin = Plugin()\n"
    )

    async def fail():
        raise RuntimeError("background-contract-failure")

    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(make_plugin(tmp_path, source))
        with pytest.raises(RuntimeError, match="background-contract-failure"):
            await ctx.resources.task(fail(), description="failed-worker")
        await asyncio.sleep(0)
        snapshot = host.resource_snapshot("resource-contract")
        assert snapshot["resources"] == ()
        assert any(
            "background-contract-failure" in error
            for error in snapshot["errors"]
        )


async def test_closed_child_scopes_release_parent_registration(tmp_path):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    source = (
        "class Plugin:\n    def register(self, ctx):\n        "
        "pass\nplugin = Plugin()\n"
    )
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(make_plugin(tmp_path, source))
        initial = ctx.resources.snapshot()["resources"]
        closed = []
        for index in range(20):
            child = ctx.resources.child(instance_id=f"restart-{index}")
            child.defer(lambda number=index: closed.append(number))
            await child.close()
            await child.close()
            assert child.closed
            assert ctx.resources.snapshot()["resources"] == initial
        assert closed == list(range(20))

        blocked = True

        async def cleanup():
            if blocked:
                raise RuntimeError("child still owns a live resource")

        child = ctx.resources.child(instance_id="retry")
        child.defer(cleanup)
        with pytest.raises(SDKError, match="still owns"):
            await child.close()
        assert not child.closed
        assert ctx.resources.snapshot()["resources"] == initial + (
            "scope::retry",
        )
        blocked = False
        await child.close()
        assert child.closed
        assert ctx.resources.snapshot()["resources"] == initial


async def test_child_release_preserves_same_owner_siblings(tmp_path):
    from qwenpaw.plugins.testing import PluginTestHost

    source = (
        "class Plugin:\n    def register(self, ctx):\n        "
        "pass\nplugin = Plugin()\n"
    )
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(make_plugin(tmp_path, source))
        first = ctx.resources.child(instance_id="same")
        second = ctx.resources.child(instance_id="same")
        await first.close()
        assert ctx.resources.snapshot()["resources"] == ("scope::same",)
        third = ctx.resources.child(instance_id="same")
        await first.close()
        assert not second.closed and not third.closed
        assert ctx.resources.snapshot()["resources"] == ("scope::same",) * 2
        await second.close()
        await third.close()
        assert ctx.resources.snapshot()["resources"] == ()


async def test_parent_and_child_concurrent_close_wait_for_one_real_cleanup(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = (
        "class Plugin:\n    def register(self, ctx):\n        "
        "pass\nplugin = Plugin()\n"
    )
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def cleanup():
        calls.append("started")
        entered.set()
        await release.wait()
        calls.append("finished")

    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(make_plugin(tmp_path, source))
        child = ctx.resources.child(instance_id="concurrent")
        child.defer(cleanup)
        direct = asyncio.create_task(child.close())
        await asyncio.wait_for(entered.wait(), 1)
        parent = asyncio.create_task(ctx.resources.close())
        try:
            await asyncio.sleep(0.02)
            assert not direct.done() and not parent.done()
            assert ctx.resources.snapshot()["resources"] == (
                "scope::concurrent",
            )
        finally:
            release.set()
            await asyncio.wait_for(asyncio.gather(direct, parent), 2)
        assert calls == ["started", "finished"]
        assert child.closed and ctx.resources.closed
        assert ctx.resources.snapshot()["resources"] == ()
