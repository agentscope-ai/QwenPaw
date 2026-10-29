# -*- coding: utf-8 -*-
"""Bound model services retain both caller and provider resource ownership."""

import asyncio

import pytest

from .test_sdk_context_services import package

from .timing import WAIT_TIMEOUT

CALLER = """
from qwenpaw.plugins.messages import ContentBlock, Message
from qwenpaw.plugins.tools import ToolSpec, ToolEvent, ToolResult

saved = None


class Plugin:
    def register(self, ctx):
        async def streaming(call, args):
            stream = call.models.stream(
                (Message("user", (ContentBlock(text="hold"),)),)
            )
            try:
                async for chunk in stream:
                    if chunk.content:
                        yield ToolEvent("delta", chunk.content)
            finally:
                await stream.aclose()
                ctx.storage.write_json("caller-closed.json", True)

        async def complete(call, args):
            result = await call.models.complete(
                (Message("user", (ContentBlock(text="hold"),)),)
            )
            return ToolResult(result.content)

        async def capture(call, args):
            global saved
            saved = call
            return ToolResult.text("captured")

        async def reuse(call, args):
            result = await saved.models.complete(
                (
                    Message(
                        "user", (ContentBlock(text="must not run"),)
                    ),
                )
            )
            return ToolResult(result.content)

        for name, handler in (
            ("bound_stream", streaming),
            ("bound_complete", complete),
            ("bound_capture", capture),
            ("bound_reuse", reuse),
        ):
            ctx.register_tool(
                ToolSpec(
                    name,
                    name,
                    {"type": "object"},
                    handler,
                    enabled=True,
                )
            )


plugin = Plugin()
"""

ASYNC_PROVIDER = """
import asyncio
from qwenpaw.plugins.messages import ContentBlock
from qwenpaw.plugins.providers import (
    ProviderSpec,
    ModelInfo,
    ModelChunk,
)


class Plugin:
    def register(self, ctx):
        async def generate(call, request):
            ctx.storage.write_json("entered.json", True)
            try:
                yield ModelChunk((ContentBlock(text="first"),))
                while not ctx.storage.read_json(
                    "release.json", False
                ):
                    await asyncio.sleep(0.01)
                yield ModelChunk(
                    (ContentBlock(text="last"),), is_last=True
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


async def load_pair(host, tmp_path, provider_source=ASYNC_PROVIDER):
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


async def test_context_model_stream_close_releases_both_plugin_owners(
    tmp_path,
):
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        provider, caller = await load_pair(host, tmp_path)
        stream = host.stream_tool(
            "bound_stream",
            {},
            workspace_id="bound",
            session_id="owned",
        )
        try:
            first = asyncio.create_task(anext(stream))
            event = await asyncio.wait_for(first, WAIT_TIMEOUT)
            assert first.done() and event.content[0].text == "first"
            for owner in ("bound-caller-owner", "bound-provider-owner"):
                assert host.resource_snapshot(owner)["active_calls"] > 0
                with pytest.raises(PluginBusyError):
                    await host.reload(owner)
        finally:
            try:
                await asyncio.wait_for(stream.aclose(), WAIT_TIMEOUT)
            finally:
                provider.storage.write_json("release.json", True)
        assert provider.storage.read_json("provider-closed.json") is True
        assert caller.storage.read_json("caller-closed.json") is True
        for owner in ("bound-caller-owner", "bound-provider-owner"):
            assert host.resource_snapshot(owner)["active_calls"] == 0
            assert (await host.reload(owner)).ok


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


async def test_finished_call_context_cannot_start_another_model_invocation(
    tmp_path,
):
    from qwenpaw.plugins import StaleContextError
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        provider, caller = await load_pair(host, tmp_path)
        assert not hasattr(
            caller,
            "models",
        ), "Top-level plugin context has no workspace"
        await host.call_tool(
            "bound_capture",
            {},
            workspace_id="bound",
            session_id="old",
        )
        with pytest.raises(StaleContextError):
            await host.call_tool(
                "bound_reuse",
                {},
                workspace_id="bound",
                session_id="new",
            )
        assert provider.storage.read_json("entered.json", False) is False


@pytest.mark.parametrize(
    "tool_timeout, model_timeout",
    [(300.0, 60.0), (60.0, 300.0)],
)
async def test_bound_model_uses_earliest_deadline(
    tmp_path,
    monkeypatch,
    tool_timeout,
    model_timeout,
):
    from qwenpaw.plugins.testing import PluginTestHost

    # Compare absolute deadlines; disk speed must not decide this test.
    # Cancellation and owner cleanup have separate lifecycle tests.
    # pylint: disable=protected-access
    provider_source = ASYNC_PROVIDER.replace(
        'ctx.storage.write_json("entered.json", True)',
        'ctx.storage.write_json("deadline.json", call.deadline)',
    )
    caller_source = f"""
import asyncio
from qwenpaw.plugins.messages import ContentBlock, Message
from qwenpaw.plugins.tools import ToolSpec, ToolResult
class Plugin:
    def register(self, ctx):
        async def complete(call, args):
            started = asyncio.get_running_loop().time()
            result = await call.models.complete(
                (Message("user", (ContentBlock(text="hold"),)),),
                timeout={model_timeout!r},
            )
            return ToolResult(result.content, metadata={{
                "parent_deadline": call.deadline,
                "started": started,
                "finished": asyncio.get_running_loop().time(),
            }})
        ctx.register_tool(ToolSpec(
            "bound_deadline", "deadline", {{"type": "object"}}, complete,
            enabled=True, timeout={tool_timeout!r},
        ))
plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        provider = await host.load(
            package(
                tmp_path / "provider",
                "deadline-provider",
                provider_source,
                ["providers", "storage"],
            ),
        )
        caller = await host.load(
            package(
                tmp_path / "caller",
                "deadline-caller",
                caller_source,
                ["tools"],
            ),
        )
        deadlines = []
        managed_stream = caller._managed_stream

        def observe_deadline(factory, label, **kwargs):
            if label == "configured model request":
                deadlines.append(kwargs.get("deadline"))
            return managed_stream(factory, label, **kwargs)

        monkeypatch.setattr(caller, "_managed_stream", observe_deadline)
        await host.configure_chat_model(
            "bound-provider",
            "bound-model",
            workspace_id="bound",
        )
        provider.storage.write_json("release.json", True)
        result = await asyncio.wait_for(
            host.call_tool("bound_deadline", {}, workspace_id="bound"),
            WAIT_TIMEOUT,
        )
        deadline = provider.storage.read_json("deadline.json")
        parent = result.metadata["parent_deadline"]
        assert deadlines == [deadline]
        assert deadline is not None and parent is not None
        assert (
            min(parent, result.metadata["started"] + model_timeout) <= deadline
        )
        assert deadline <= min(
            parent,
            result.metadata["finished"] + model_timeout,
        )
        assert provider.storage.read_json("provider-closed.json") is True
        for owner in ("deadline-provider", "deadline-caller"):
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
