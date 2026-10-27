# -*- coding: utf-8 -*-
"""Public HTTP storage responsiveness and official template concurrency."""

import asyncio
import os
import shutil
import threading
import time
from pathlib import Path

import pytest

from .sdk_author_fixture import make_plugin

from .timing import WAIT_TIMEOUT, wait_for_thread_progress

pytestmark = pytest.mark.p1

APP_SOURCE = """
from qwenpaw.plugins.apps import PawApp

class Plugin:
    def register(self, context):
        context.register_app(
            PawApp(app_id="storage-probe").enable_standard_capabilities()
        )

plugin = Plugin()
"""


@pytest.mark.parametrize("operation", ["get", "set", "delete", "keys"])
async def test_standard_http_storage_keeps_loop_responsive(
    tmp_path,
    monkeypatch,
    operation,
):
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, APP_SOURCE, ["apps", "storage"]))
        path = "/api/storage-probe/storage/item.json"
        assert (
            await host.request("PUT", path, json={"value": 7})
        ).status == 200
        ticks, observations = [], []

        async def heartbeat():
            while True:
                ticks.append(time.monotonic())
                await asyncio.sleep(0.005)

        target, name = {
            "get": (Path, "read_bytes"),
            "set": (os, "fsync"),
            "delete": (Path, "unlink"),
            "keys": (Path, "rglob"),
        }[operation]
        original = getattr(target, name)

        def observe_delay():
            before = len(ticks)
            wait_for_thread_progress(lambda: len(ticks) > before)
            observations.append(
                (threading.current_thread().name, len(ticks) - before),
            )

        def slow_io(*args, **kwargs):
            if operation == "keys":

                def entries():
                    observe_delay()
                    yield from original(*args, **kwargs)

                return entries()
            if operation == "set" or args[0].name == "item.json":
                observe_delay()
            return original(*args, **kwargs)

        heart = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.01)
        try:
            with monkeypatch.context() as patch:
                patch.setattr(target, name, slow_io)
                response = await host.request(
                    {
                        "get": "GET",
                        "set": "PUT",
                        "delete": "DELETE",
                        "keys": "GET",
                    }[operation],
                    path.rsplit("/", 1)[0] if operation == "keys" else path,
                    **({"json": {"value": 8}} if operation == "set" else {}),
                )
            assert response.status == 200
            assert observations and all(
                thread != "MainThread" and delta > 0
                for thread, delta in observations
            ), observations
            if operation == "get":
                assert response.json() == {"value": 7}
            elif operation == "keys":
                assert response.json() == {"keys": ["item.json"]}
            else:
                current = await host.request("GET", path)
                assert current.json() == {
                    "value": 8 if operation == "set" else None,
                }
        finally:
            heart.cancel()
            await asyncio.gather(heart, return_exceptions=True)


async def test_official_template_concurrent_counts_survive_reload(
    tmp_path,
    monkeypatch,
):
    import qwenpaw.plugins
    from qwenpaw.plugins.testing import PluginTestHost

    template = Path(qwenpaw.plugins.__file__).parent / "templates" / "hello"
    package = tmp_path / "hello"
    shutil.copytree(template, package)
    original = Path.read_bytes

    def slow_read(path):
        if path.name == "count.json":
            time.sleep(0.03)
        return original(path)

    def count(result):
        text = "".join(block.text for block in result.content)
        return int(text.rsplit("(", 1)[1].rstrip(")"))

    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(package)
        with monkeypatch.context() as patch:
            patch.setattr(Path, "read_bytes", slow_read)
            results = await asyncio.gather(
                *(
                    host.call_tool(
                        "hello_sdk",
                        {"name": "parallel"},
                        workspace_id="sales",
                    )
                    for _ in range(20)
                ),
            )
        assert sorted(map(count, results)) == list(range(1, 21))
        other = await host.call_tool(
            "hello_sdk",
            {"name": "other"},
            workspace_id="support",
        )
        assert count(other) == 1
        import json

        plugin_id = json.loads((package / "plugin.json").read_text())["id"]
        assert (await host.reload(plugin_id)).ok
        retained = await host.call_tool(
            "hello_sdk",
            {"name": "retained"},
            workspace_id="sales",
        )
        assert count(retained) == 21


async def test_cancelled_http_write_blocks_reload_until_disk_finishes(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.testing import PluginTestHost

    entered, release, finished = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    original = os.fsync
    threads = []

    def controlled_fsync(fd):
        threads.append(threading.current_thread().name)
        entered.set()
        assert release.wait(
            WAIT_TIMEOUT * 2,
        ), "Test did not release actual disk operation"
        result = original(fd)
        finished.set()
        return result

    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, APP_SOURCE, ["apps", "storage"]))
        path = "/api/storage-probe/storage/item.json"
        assert (
            await host.request("PUT", path, json={"value": 0})
        ).status == 200
        task = None
        try:
            with monkeypatch.context() as patch:
                patch.setattr(os, "fsync", controlled_fsync)
                task = asyncio.create_task(
                    host.request("PUT", path, json={"value": 9}),
                )
                async with asyncio.timeout(WAIT_TIMEOUT):
                    while not entered.is_set():
                        await asyncio.sleep(0.005)
                task.cancel()
                await asyncio.sleep(0.02)
                task.cancel()
                with pytest.raises(PluginBusyError):
                    await host.reload(
                        "extension-contract",
                        interrupt_tasks=True,
                    )
                assert not finished.is_set()
                assert (
                    host.resource_snapshot("extension-contract")[
                        "active_calls"
                    ]
                    > 0
                )
                release.set()
                assert await asyncio.to_thread(finished.wait, WAIT_TIMEOUT)
                await asyncio.gather(task, return_exceptions=True)
            assert threads and all(
                thread != "MainThread" for thread in threads
            )
            assert (
                await host.reload("extension-contract", interrupt_tasks=True)
            ).ok
            # Cancellation invalidates the scope before atomic replacement.
            assert (await host.request("GET", path)).json() == {"value": 0}
            assert (
                await host.request("PUT", path, json={"value": 10})
            ).status == 200
            assert (await host.request("GET", path)).json() == {"value": 10}
            assert (
                host.resource_snapshot("extension-contract")["active_calls"]
                == 0
            )
        finally:
            release.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
