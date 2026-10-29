# -*- coding: utf-8 -*-
"""Public memory backend through real service ownership and queue worker."""

import asyncio

import pytest

from .sdk_author_fixture import make_plugin

from .timing import WAIT_TIMEOUT

SOURCE = """
from pathlib import Path
from qwenpaw.plugins.memory import MemorySpec
from qwenpaw.plugins.tools import ToolResult


class Backend:
    async def start(self, call):
        assert not hasattr(call, "workspace") and not hasattr(
            call, "agent"
        )
        assert call.config.secret("token") == "test-memory-token"
        call.storage.write_json("started.json", call.workspace_id)

    async def search(self, call, query, max_results):
        return ToolResult.text(
            f"{call.workspace_id}:{query}:{max_results}"
        )

    async def remember(self, call, messages):
        value = [message.content[0].text for message in messages]
        call.storage.write_json("remembered.json", value)
        return "stored:" + ",".join(value)

    async def close(self, call):
        directory = call.config.get("directory")
        if (
            directory
            and not (Path(directory) / "allow-close").exists()
        ):
            return False
        call.storage.write_json("closed.json", True)
        return True


class Plugin:
    def register(self, ctx):
        ctx.register_memory(
            MemorySpec(
                "sdk-memory",
                "SDK memory",
                Backend,
                config_schema={
                    "type": "object",
                    "properties": {
                        "token": {"type": "string"},
                        "directory": {"type": "string"},
                    },
                    "required": ["token"],
                },
                secrets=("token",),
            )
        )


plugin = Plugin()
"""


async def test_memory_search_remember_queue_and_workspace_instances(tmp_path):
    from qwenpaw.plugins.messages import ContentBlock, Message
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, SOURCE, ["memory", "storage"]))
        for workspace in ("one", "two"):
            await host.start_memory(
                "sdk-memory",
                workspace_id=workspace,
                config={"token": "test-memory-token"},
            )
            result = await host.search_memory(
                "needle",
                workspace_id=workspace,
                max_results=2,
            )
            assert result.content[0].text == f"{workspace}:needle:2"
        messages = (Message("user", (ContentBlock(text="important"),)),)
        assert (
            await host.remember(messages, workspace_id="one")
            == "stored:important"
        )
        task_id = await host.submit_memory(messages, workspace_id="two")
        async with asyncio.timeout(WAIT_TIMEOUT):
            while True:
                tasks = await host.memory_tasks(workspace_id="two")
                task = next(
                    (item for item in tasks if item.task_id == task_id),
                    None,
                )
                if task and task.status in {
                    "completed",
                    "failed",
                    "cancelled",
                }:
                    break
                await asyncio.sleep(0.01)
        assert task.status == "completed" and task.result == "stored:important"
        assert await host.memory_tasks(workspace_id="one") == ()
        for workspace in ("one", "two"):
            await host.stop_memory(workspace_id=workspace)
        assert (await host.reload("extension-contract")).ok


async def test_memory_failed_close_keeps_live_owner_and_blocks_replacement(
    tmp_path,
):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, SOURCE, ["memory", "storage"]))
        await host.start_memory(
            "sdk-memory",
            config={"token": "test-memory-token", "directory": str(tmp_path)},
        )
        try:
            with pytest.raises(SDKError, match="incomplete stop"):
                await host.stop_memory()
            # A failed stop must not make a second backend appear safely
            # installable.
            result = await host.reload("extension-contract")
            assert result.ok is False and result.unchanged is True
            assert result.errors
            assert (await host.search_memory("still-live")).content[
                0
            ].text == "test:still-live:5"
        finally:
            (tmp_path / "allow-close").touch()
            await host.stop_memory()
        assert (await host.reload("extension-contract")).ok


async def test_memory_partial_start_cleans_backend_and_managed_tasks(tmp_path):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
import asyncio
from pathlib import Path
from qwenpaw.plugins.memory import MemorySpec
from qwenpaw.plugins.tools import ToolResult


class Backend:
    async def start(self, call):
        async def worker():
            try:
                await asyncio.sleep(100)
            finally:
                (
                    Path(call.config.get("directory"))
                    / "worker-stopped"
                ).touch()

        call.resources.task(worker(), "partly-started-worker")
        await asyncio.sleep(0)
        raise RuntimeError("intentional memory start failure")

    async def search(self, call, query, max_results):
        return ToolResult.text("unused")

    async def remember(self, call, messages):
        return "unused"

    async def close(self, call):
        (
            Path(call.config.get("directory")) / "backend-closed"
        ).touch()
        return True


class Plugin:
    def register(self, ctx):
        ctx.register_memory(
            MemorySpec("sdk-partial-memory", "Partial", Backend)
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, source, ["memory", "resources"]))
        with pytest.raises(SDKError):
            await host.start_memory(
                "sdk-partial-memory",
                config={"directory": str(tmp_path)},
            )
        assert (tmp_path / "backend-closed").exists()
        assert (tmp_path / "worker-stopped").exists()
        host.assert_quiescent("extension-contract")
        # Failed startup keeps the persisted selection, just like the real
        # host.
        blocked = await host.reload("extension-contract")
        assert not blocked.ok and blocked.unchanged and blocked.errors
        await host.stop_memory()
        assert (await host.reload("extension-contract")).ok


async def test_sync_memory_search_uses_current_invocation_cancellation(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
import time
from pathlib import Path
from qwenpaw.plugins.memory import MemorySpec
from qwenpaw.plugins.tools import ToolResult
class Backend:
    async def start(self, call):
        pass
    def search(self, call, query, max_results):
        root = Path(call.config.get("directory"))
        (root / "search-entered").touch()
        try:
            while not call.cancelled and not (root / "release").exists():
                time.sleep(0.01)
            if call.cancelled:
                (root / "cancel-observed").touch()
            return ToolResult.text("done")
        finally:
            (root / "search-stopped").touch()
    async def remember(self, call, messages):
        return "unused"
    async def close(self, call):
        return True
class Plugin:
    def register(self, ctx):
        ctx.register_memory(MemorySpec("sync-memory", "Sync memory", Backend))
plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, source, ["memory"]))
        await host.start_memory(
            "sync-memory",
            config={"directory": str(tmp_path)},
        )
        query = asyncio.create_task(host.search_memory("cancel this search"))
        try:
            async with asyncio.timeout(WAIT_TIMEOUT):
                while True:
                    if (tmp_path / "search-entered").exists():
                        break
                    await asyncio.sleep(0.01)
            assert (tmp_path / "search-entered").exists()
            query.cancel()
            done, _ = await asyncio.wait({query}, timeout=WAIT_TIMEOUT)
            assert (
                query in done
            ), "Sync memory worker retained the start task cancellation state"
            with pytest.raises(asyncio.CancelledError):
                await query
            assert (tmp_path / "cancel-observed").exists()
            assert (tmp_path / "search-stopped").exists()
        finally:
            (tmp_path / "release").touch()
            await asyncio.gather(query, return_exceptions=True)
            await host.stop_memory()
        assert (await host.reload("extension-contract")).ok
