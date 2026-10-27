# -*- coding: utf-8 -*-
"""Author-facing integration tests: imports are restricted to public SDK APIs.

The fixture is a minimal plugin, independent of the local acceptance projects.
PluginTestHost must use the real host lifecycle for meaningful tests.
"""

import asyncio
import json

import pytest

from .timing import WAIT_TIMEOUT

SOURCE = """
import asyncio
from pathlib import Path
from qwenpaw.plugins.messages import ContentBlock
from qwenpaw.plugins.tools import ToolEvent, ToolResult, ToolSpec


class Plugin:
    def register(self, ctx):
        async def echo(call, arguments):
            return ToolResult(
                content=(ContentBlock(text=arguments["text"]),),
                metadata={
                    "plugin_id": call.plugin_id,
                    "generation": call.generation,
                    "workspace_id": call.workspace_id,
                    "session_id": call.session_id,
                },
            )

        async def stream(call, arguments):
            try:
                yield ToolEvent(
                    kind="delta",
                    content=(
                        ContentBlock(type="text", text="first"),
                    ),
                )
                await asyncio.Event().wait()
            finally:
                Path(ctx.config.get("marker")).write_text(
                    "stream-closed"
                )

        ctx.register_tool(
            ToolSpec(
                name="sdk_contract_echo",
                description="Echo the supplied text",
                input_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
                handler=echo,
                enabled=True,
            )
        )
        ctx.register_tool(
            ToolSpec(
                name="sdk_contract_stream",
                description="A cancellable stream",
                input_schema={"type": "object"},
                handler=stream,
                enabled=True,
            )
        )


plugin = Plugin()
"""


def make_plugin(tmp_path, source=SOURCE):
    root = tmp_path / "author-plugin"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": "author-contract",
                "version": "1.0.0",
                "entry": {"backend": "main.py"},
                "sdk": {"version": "1.0", "capabilities": ["tools"]},
            },
        ),
        encoding="utf-8",
    )
    (root / "main.py").write_text(source, encoding="utf-8")
    return root


async def test_author_load_call_reload_and_stale_context(tmp_path):
    from qwenpaw.plugins import PluginContext, StaleContextError
    from qwenpaw.plugins.testing import PluginTestHost
    from qwenpaw.plugins.tools import ToolResult, ToolSpec

    root = make_plugin(tmp_path)
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            root,
            config={"marker": str(tmp_path / "closed")},
        )
        assert isinstance(ctx, PluginContext)
        assert not hasattr(ctx, "host")
        assert not hasattr(ctx, "workspace")
        assert not hasattr(ctx, "registry")
        result = await host.call_tool("sdk_contract_echo", {"text": "hello"})
        assert isinstance(result, ToolResult)
        assert [(block.type, block.text) for block in result.content] == [
            ("text", "hello"),
        ]
        assert not result.is_error
        report = await host.reload("author-contract")
        assert report.ok, report.errors
        assert host.context("author-contract") is not ctx
        with pytest.raises(StaleContextError):
            ctx.register_tool(
                ToolSpec(
                    name="stale_tool",
                    description="must not register",
                    input_schema={"type": "object"},
                    handler=lambda *_: ToolResult.text("stale"),
                ),
            )
        assert (
            await host.call_tool("sdk_contract_echo", {"text": "new"})
        ).content[0].text == "new"
        report = await host.unload("author-contract")
        assert report.clean and report.quiescent
        host.assert_quiescent("author-contract")
        with pytest.raises((KeyError, RuntimeError)):
            await host.call_tool("sdk_contract_echo", {"text": "gone"})


async def test_stream_is_busy_between_items_and_close_releases_it(tmp_path):
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.testing import PluginTestHost

    marker = tmp_path / "closed"
    root = make_plugin(tmp_path)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(root, config={"marker": str(marker)})
        stream = host.stream_tool("sdk_contract_stream", {})
        try:
            first = await anext(stream)
            assert first.kind == "delta" and first.content[0].text == "first"
            with pytest.raises(PluginBusyError):
                await host.reload("author-contract")
            assert not marker.exists()
        finally:
            await stream.aclose()
        assert marker.read_text() == "stream-closed"
        report = await host.reload("author-contract")
        assert report.ok, report.errors


async def test_stream_consumer_cancellation_closes_plugin_generator(tmp_path):
    from qwenpaw.plugins.testing import PluginTestHost

    marker = tmp_path / "closed"
    root = make_plugin(tmp_path)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(root, config={"marker": str(marker)})
        entered = asyncio.Event()

        async def consume():
            async for item in host.stream_tool("sdk_contract_stream", {}):
                assert item.kind == "delta"
                entered.set()

        task = asyncio.create_task(consume())
        await asyncio.wait_for(entered.wait(), WAIT_TIMEOUT)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert marker.read_text() == "stream-closed"
        report = await host.unload("author-contract")
        assert report.clean and report.quiescent
        host.assert_quiescent("author-contract")


async def test_three_idle_reloads_leave_one_callable_generation(tmp_path):
    from qwenpaw.plugins.testing import PluginTestHost

    root = make_plugin(tmp_path)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(root, config={"marker": str(tmp_path / "closed")})
        initial = host.resource_snapshot("author-contract")
        previous_generation = initial["owner"].generation
        for index in range(3):
            report = await host.reload("author-contract")
            assert report.ok, (index, report.errors)
            result = await host.call_tool(
                "sdk_contract_echo",
                {"text": str(index)},
            )
            assert result.content[0].text == str(index)
            snapshot = host.resource_snapshot("author-contract")
            assert snapshot["resources"] == initial["resources"]
            assert snapshot["active_calls"] == 0
            assert snapshot["owner"].generation > previous_generation
            previous_generation = snapshot["owner"].generation
        report = await host.unload("author-contract")
        assert report.clean and report.quiescent
        host.assert_quiescent("author-contract")


async def test_tool_argument_validation_and_invocation_identity(tmp_path):
    from qwenpaw.plugins import ToolInputError
    from qwenpaw.plugins.testing import PluginTestHost

    root = make_plugin(tmp_path)
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(root)
        for invalid in ({}, {"text": 42}):
            with pytest.raises(ToolInputError):
                await host.call_tool("sdk_contract_echo", invalid)
        result = await host.call_tool(
            "sdk_contract_echo",
            {"text": "identity"},
            workspace_id="workspace-b",
            session_id="session-c",
        )
        assert result.metadata == {
            "plugin_id": "author-contract",
            "generation": ctx.generation,
            "workspace_id": "workspace-b",
            "session_id": "session-c",
        }
        assert host.resource_snapshot("author-contract")["active_calls"] == 0


async def test_stream_suspended_after_short_lived_task_still_blocks_reload(
    tmp_path,
):
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.testing import PluginTestHost

    root = make_plugin(tmp_path)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(root, config={"marker": str(tmp_path / "closed")})
        stream = host.stream_tool("sdk_contract_stream", {})
        try:
            first_call = asyncio.create_task(anext(stream))
            first = await first_call
            assert first_call.done() and first.kind == "delta"
            assert (
                host.resource_snapshot("author-contract")["active_calls"] == 1
            )
            with pytest.raises(PluginBusyError):
                await host.reload("author-contract")
        finally:
            await stream.aclose()
        assert host.resource_snapshot("author-contract")["active_calls"] == 0
        assert (await host.reload("author-contract")).ok


async def test_sync_tool_observes_cancellation_and_really_exits(tmp_path):
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
import time
from pathlib import Path
from qwenpaw.plugins.tools import ToolResult, ToolSpec


class Plugin:
    def register(self, ctx):
        def work(call, arguments):
            directory = Path(ctx.config.get("directory"))
            try:
                assert not call.cancelled
                (directory / "started").touch()
                while not (directory / "release").exists():
                    call.check_cancelled()
                    time.sleep(0.01)
                return ToolResult.text("released")
            finally:
                (directory / "exited").touch()

        ctx.register_tool(
            ToolSpec(
                name="sdk_sync_cancel",
                description="Cooperatively cancellable synchronous work",
                input_schema={"type": "object"},
                handler=work,
                enabled=True,
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(tmp_path, source),
            config={"directory": str(tmp_path)},
        )
        invocation = asyncio.create_task(host.call_tool("sdk_sync_cancel", {}))
        try:
            async with asyncio.timeout(WAIT_TIMEOUT):
                while True:
                    if (tmp_path / "started").exists() or invocation.done():
                        break
                    await asyncio.sleep(0.01)
            assert (tmp_path / "started").exists(), (
                invocation.exception()
                if invocation.done()
                else "Tool did not start"
            )
            invocation.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(invocation, WAIT_TIMEOUT)
            assert (tmp_path / "exited").exists()
            assert (
                host.resource_snapshot("author-contract")["active_calls"] == 0
            )
        finally:
            (tmp_path / "release").touch()
            await asyncio.gather(invocation, return_exceptions=True)


async def test_denied_tool_never_runs_handler(tmp_path):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    source = SOURCE.replace(
        "async def echo(call, arguments):",
        (
            "async def echo(call, arguments):\n            "
            'Path(ctx.config.get("marker")).touch()'
        ),
    )
    marker = tmp_path / "handler-ran"
    async with PluginTestHost(
        tmp_path / "host",
        tool_policy={"sdk_contract_echo": "deny"},
    ) as host:
        await host.load(
            make_plugin(tmp_path, source),
            config={"marker": str(marker)},
        )
        with pytest.raises(SDKError):
            await host.call_tool("sdk_contract_echo", {"text": "denied"})
        assert not marker.exists()
        assert host.resource_snapshot("author-contract")["active_calls"] == 0


@pytest.mark.parametrize("approved", [False, True])
async def test_approval_gates_handler_execution(tmp_path, approved):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    source = SOURCE.replace(
        "async def echo(call, arguments):",
        (
            "async def echo(call, arguments):\n            "
            'Path(ctx.config.get("marker")).touch()'
        ),
    )
    marker = tmp_path / "handler-ran"
    async with PluginTestHost(
        tmp_path / "host",
        tool_policy={"sdk_contract_echo": "ask"},
    ) as host:
        await host.load(
            make_plugin(tmp_path, source),
            config={"marker": str(marker)},
        )
        invocation = asyncio.create_task(
            host.call_tool("sdk_contract_echo", {"text": "approved"}),
        )
        try:
            requests = []
            async with asyncio.timeout(WAIT_TIMEOUT):
                while True:
                    requests = await host.approval_requests(session_id="test")
                    if requests or invocation.done():
                        break
                    await asyncio.sleep(0.01)
            assert len(requests) == 1
            assert requests[0].tool_name == "sdk_contract_echo"
            assert not marker.exists() and not invocation.done()
            await host.resolve_approval(
                requests[0].request_id,
                approved=approved,
            )
            if approved:
                result = await asyncio.wait_for(invocation, WAIT_TIMEOUT)
                assert result.content[0].text == "approved" and marker.exists()
            else:
                with pytest.raises(SDKError):
                    await asyncio.wait_for(invocation, WAIT_TIMEOUT)
                assert not marker.exists()
        finally:
            if not invocation.done():
                invocation.cancel()
            await asyncio.gather(invocation, return_exceptions=True)


async def test_unsupported_tool_content_raises_instead_of_disappearing(
    tmp_path,
):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.messages import ContentBlock
from qwenpaw.plugins.tools import ToolResult, ToolSpec


class Plugin:
    def register(self, ctx):
        async def unsupported(call, args):
            return ToolResult(
                (
                    ContentBlock(
                        type="thinking", text="must-not-disappear"
                    ),
                )
            )

        ctx.register_tool(
            ToolSpec(
                name="sdk_unsupported_content",
                description="Protocol violation",
                input_schema={"type": "object"},
                handler=unsupported,
                enabled=True,
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, source))
        with pytest.raises(SDKError):
            await host.call_tool("sdk_unsupported_content", {})
        assert host.resource_snapshot("author-contract")["active_calls"] == 0


async def test_tool_deadline_cancels_work_and_reports_public_error(tmp_path):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
import asyncio
from qwenpaw.plugins.tools import ToolSpec, ToolResult


class Plugin:
    def register(self, ctx):
        async def slow(call, args):
            assert call.deadline is not None
            now = asyncio.get_running_loop().time()
            assert now < call.deadline <= now + 0.05
            try:
                await asyncio.sleep(10)
                return ToolResult.text("must not finish")
            finally:
                ctx.storage.write_json(
                    "deadline-cancelled.json", call.cancelled
                )

        ctx.register_tool(
            ToolSpec(
                "deadline_tool",
                "deadline",
                {"type": "object"},
                slow,
                enabled=True,
                timeout=0.05,
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(make_plugin(tmp_path, source=source))
        with pytest.raises(SDKError, match="deadline"):
            await asyncio.wait_for(
                host.call_tool("deadline_tool", {}),
                WAIT_TIMEOUT,
            )
        assert ctx.storage.read_json("deadline-cancelled.json") is True
        assert host.resource_snapshot("author-contract")["active_calls"] == 0
        assert (await host.reload("author-contract")).ok


async def test_tool_result_metadata_keys_are_not_reserved_by_host_bridge(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    expected = {
        "_sdk_event": "author-event",
        "is_error": "author-value",
        "_sdk_attachment_previews": {"nested": ["author-value"]},
    }
    source = """
from qwenpaw.plugins.tools import ToolSpec, ToolResult


class Plugin:
    def register(self, ctx):
        async def result(call, args):
            return ToolResult(metadata=args)

        ctx.register_tool(
            ToolSpec(
                "metadata_echo",
                "metadata",
                {"type": "object"},
                result,
                enabled=True,
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, source))
        result = await host.call_tool("metadata_echo", expected)
        assert result.metadata == expected
        assert result.is_error is False


@pytest.mark.parametrize("streaming", [False, True])
async def test_adjacent_text_with_different_metadata_is_explicitly_rejected(
    tmp_path,
    streaming,
):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.messages import ContentBlock
from qwenpaw.plugins.tools import ToolSpec, ToolResult, ToolEvent


class Plugin:
    def register(self, ctx):
        async def result(call, args):
            return ToolResult(
                (
                    ContentBlock(
                        text="first", metadata={"author": "first"}
                    ),
                    ContentBlock(text="second"),
                )
            )

        async def stream(call, args):
            yield ToolEvent(
                "delta",
                (
                    ContentBlock(
                        text="first", metadata={"author": "first"}
                    ),
                ),
            )
            yield ToolEvent("delta", (ContentBlock(text="second"),))

        ctx.register_tool(
            ToolSpec(
                "metadata_conflict",
                "metadata",
                {"type": "object"},
                HANDLER,
                enabled=True,
            )
        )


plugin = Plugin()
""".replace(
        "HANDLER",
        "stream" if streaming else "result",
    )
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, source))
        with pytest.raises(SDKError):
            await host.call_tool("metadata_conflict", {})
        host.assert_quiescent("author-contract")
