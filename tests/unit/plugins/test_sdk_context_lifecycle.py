# -*- coding: utf-8 -*-
"""Bound model services retain both caller and provider resource ownership."""

import asyncio
import json

import pytest

from .timing import WAIT_TIMEOUT


def package(root, plugin_id, source, capabilities):
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": plugin_id,
                "version": "1.0.0",
                "entry": {"backend": "main.py"},
                "sdk": {"version": "1.0", "capabilities": capabilities},
            },
        ),
    )
    (root / "main.py").write_text(source)
    return root


CALLER = """
from qwenpaw.plugins.messages import ContentBlock, Message
from qwenpaw.plugins.tools import ToolSpec, ToolResult

class Plugin:
    def register(self, ctx):
        async def complete(call, args):
            result = await call.models.complete(
                (Message("user", (ContentBlock(text="hold"),)),)
            )
            return ToolResult(result.content)
        ctx.register_tool(ToolSpec(
            "bound_complete", "bound_complete", {"type": "object"},
            complete, enabled=True,
        ))
plugin = Plugin()
"""


SYNC_PROVIDER = """
import time
from qwenpaw.plugins.messages import ContentBlock
from qwenpaw.plugins.providers import (
    ProviderSpec,
    ModelInfo,
    ModelChunk,
)


class Plugin:
    def register(self, ctx):
        def generate(call, request):
            ctx.storage.write_json("entered.json", True)
            try:
                while not ctx.storage.read_json(
                    "release.json", False
                ):
                    if call.cancelled:
                        ctx.storage.write_json(
                            "cancel-seen.json", True
                        )
                    time.sleep(0.01)
                return ModelChunk(
                    (ContentBlock(text="released"),), is_last=True
                )
            finally:
                ctx.storage.write_json("provider-closed.json", True)

        ctx.register_provider(
            ProviderSpec(
                "bound-provider",
                "Bound",
                generate,
                models=(ModelInfo("bound-model", "Bound"),),
                require_api_key=False,
            )
        )


plugin = Plugin()
"""


async def until(predicate):
    async with asyncio.timeout(WAIT_TIMEOUT):
        while not predicate():
            await asyncio.sleep(0.01)


async def load_pair(host, tmp_path, provider_source):
    provider = await host.load(
        package(
            tmp_path / "provider",
            "bound-provider-owner",
            provider_source,
            ["providers", "storage"],
        ),
    )
    caller = await host.load(
        package(
            tmp_path / "caller",
            "bound-caller-owner",
            CALLER,
            ["tools", "storage"],
        ),
    )
    await host.configure_chat_model(
        "bound-provider",
        "bound-model",
        workspace_id="bound",
    )
    return provider, caller


async def test_context_model_cancel_waits_for_actual_sync_provider_worker(
    tmp_path,
):
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        provider, _ = await load_pair(host, tmp_path, SYNC_PROVIDER)
        task = asyncio.create_task(
            host.call_tool(
                "bound_complete",
                {},
                workspace_id="bound",
                session_id="sync",
            ),
        )
        try:
            await until(
                lambda: provider.storage.read_json("entered.json", False),
            )
            task.cancel()
            await until(
                lambda: provider.storage.read_json("cancel-seen.json", False),
            )
            assert (
                not task.done()
            ), "Cancelled caller returned while provider worker was still live"
            for owner in ("bound-caller-owner", "bound-provider-owner"):
                assert host.resource_snapshot(owner)["active_calls"] > 0
                with pytest.raises(PluginBusyError):
                    await host.reload(owner)
        finally:
            provider.storage.write_json("release.json", True)
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, WAIT_TIMEOUT)
        assert provider.storage.read_json("provider-closed.json") is True
        for owner in ("bound-caller-owner", "bound-provider-owner"):
            assert host.resource_snapshot(owner)["active_calls"] == 0
            assert (await host.reload(owner)).ok


async def test_failed_model_scope_cleanup_keeps_ownership_until_retry(
    tmp_path,
):
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.testing import PluginTestHost

    provider_source = """
from qwenpaw.plugins.messages import ContentBlock
from qwenpaw.plugins.providers import (
    ProviderSpec,
    ModelInfo,
    ModelChunk,
)


class Plugin:
    def register(self, ctx):
        async def generate(call, request):
            async def cleanup():
                ctx.storage.write_json(
                    "cleanup-attempts.json",
                    ctx.storage.read_json(
                        "cleanup-attempts.json", 0
                    )
                    + 1,
                )
                call.logger.info(
                    "model-cleanup-log", fields={"phase": "cleanup"}
                )
                if not ctx.storage.read_json(
                    "allow-close.json", False
                ):
                    raise RuntimeError("model cleanup refused")
                ctx.storage.write_json(
                    "cleanup-finished.json", True
                )

            call.resources.defer(cleanup, "model-owned-cleanup")
            yield ModelChunk(
                (ContentBlock(text="result"),), is_last=True
            )

        ctx.register_provider(
            ProviderSpec(
                "bound-provider",
                "Bound",
                generate,
                models=(ModelInfo("bound-model", "Bound"),),
                require_api_key=False,
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        provider, _ = await load_pair(host, tmp_path, provider_source)
        task = asyncio.create_task(
            host.call_tool("bound_complete", {}, workspace_id="bound"),
        )
        try:
            await until(
                lambda: provider.storage.read_json("cleanup-attempts.json", 0)
                > 0,
            )
            assert (
                provider.storage.read_json("cleanup-finished.json", False)
                is False
            )
            assert host.resource_snapshot("bound-provider-owner")["resources"]
            assert (
                not task.done()
            ), "Cleanup failure must not release the live model owner"
            for owner in ("bound-provider-owner", "bound-caller-owner"):
                try:
                    report = await host.reload(owner)
                except PluginBusyError:
                    pass
                else:
                    assert (
                        not report.ok
                    ), "Failed owned cleanup must block replacement"
        finally:
            provider.storage.write_json("allow-close.json", True)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, WAIT_TIMEOUT)
        assert provider.storage.read_json("cleanup-finished.json") is True
        for owner in ("bound-caller-owner", "bound-provider-owner"):
            assert host.resource_snapshot(owner)["active_calls"] == 0
            assert (await host.reload(owner)).ok
