# -*- coding: utf-8 -*-
"""Public Command, Hook, and Prompt contracts through the real test host."""

import asyncio

import pytest


from .sdk_author_fixture import make_plugin

from .timing import WAIT_TIMEOUT


async def test_command_alias_reply_and_release(tmp_path):
    from qwenpaw.plugins.messages import Message
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.commands import CommandResult, CommandSpec
from qwenpaw.plugins.messages import ContentBlock, Message


class Plugin:
    def register(self, ctx):
        async def greet(call, args):
            assert not hasattr(call, "workspace") and not hasattr(
                call, "agent"
            )
            return CommandResult(
                action="reply",
                message=Message(
                    role="assistant",
                    content=(ContentBlock(text=args),),
                    metadata={
                        "workspace": call.workspace_id,
                        "session": call.session_id,
                    },
                ),
            )

        ctx.register_command(
            CommandSpec(
                name="sdkgreet", handler=greet, aliases=("sdkhi",)
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, source, ["commands"]))
        result = await host.call_command(
            "/sdkhi hello author",
            workspace_id="one",
            session_id="conversation",
        )
        assert isinstance(result, Message)
        assert result.content[0].text == "hello author"
        assert result.metadata == {
            "workspace": "one",
            "session": "conversation",
        }
        assert (await host.reload("extension-contract")).ok
        assert (await host.call_command("/sdkgreet after reload")).content[
            0
        ].text == "after reload"
        assert (await host.unload("extension-contract")).quiescent
        assert await host.call_command("/sdkhi removed") is None


async def test_hook_receives_public_messages_and_replaces_permitted_input(
    tmp_path,
):
    from qwenpaw.plugins.hooks import HookPhase
    from qwenpaw.plugins.messages import ContentBlock, Message
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.hooks import HookPhase, HookResult, HookSpec
from qwenpaw.plugins.messages import ContentBlock, Message


class Plugin:
    def register(self, ctx):
        async def rewrite(call):
            assert isinstance(call.messages[0], Message)
            assert call.messages[0].content[0].text == "original"
            assert not hasattr(call, "agent") and not hasattr(
                call, "workspace"
            )
            assert call.deadline is not None
            return HookResult(
                replace_input=(
                    Message(
                        "user", (ContentBlock(text="rewritten"),)
                    ),
                )
            )

        ctx.register_hook(
            HookSpec(
                name="rewrite",
                phase=HookPhase.PRE_DISPATCH,
                handler=rewrite,
            )
        )


plugin = Plugin()
"""
    original = (Message("user", (ContentBlock(text="original"),)),)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, source, ["hooks"]))
        result = await host.run_hooks(
            HookPhase.PRE_DISPATCH,
            messages=original,
        )
        assert result.replace_input[0].content[0].text == "rewritten"
        assert original[0].content[0].text == "original"
        await host.unload("extension-contract")
        result = await host.run_hooks(
            HookPhase.PRE_DISPATCH,
            messages=original,
        )
        assert result.replace_input is None


async def test_hook_priority_and_failed_observer_do_not_abort_remaining_hooks(
    tmp_path,
    caplog,
):
    from qwenpaw.plugins.hooks import HookPhase
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.hooks import HookPhase, HookResult, HookSpec


class Plugin:
    def register(self, ctx):
        async def later(call):
            trace = ctx.storage.read_json("trace.json", [])
            ctx.storage.write_json("trace.json", trace + ["later"])
            return HookResult()

        async def earlier(call):
            ctx.storage.write_json("trace.json", ["earlier"])
            raise RuntimeError("public-hook-probe-error")

        ctx.register_hook(
            HookSpec(
                name="late",
                phase=HookPhase.PRE_EXECUTE,
                handler=later,
                priority=200,
            )
        )
        ctx.register_hook(
            HookSpec(
                name="early",
                phase=HookPhase.PRE_EXECUTE,
                handler=earlier,
                priority=10,
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(tmp_path, source, ["hooks", "storage"]),
        )
        result = await host.run_hooks(HookPhase.PRE_EXECUTE, messages=())
        assert result.action == "continue"
        assert ctx.storage.read_json("trace.json") == ["earlier", "later"]
        assert "public-hook-probe-error" in caplog.text
        assert (
            host.resource_snapshot("extension-contract")["active_calls"] == 0
        )


async def test_prompt_contribution_is_workspace_scoped_and_retractable(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.prompts import PromptSpec


class Plugin:
    def register(self, ctx):
        ctx.register_prompt(
            PromptSpec(
                name="public-style",
                text="SDK_SCOPE_MARKER_617",
                workspace_id="one",
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, source, ["prompts"]))
        one = await host.build_prompt(workspace_id="one")
        two = await host.build_prompt(workspace_id="two")
        assert one.count("SDK_SCOPE_MARKER_617") == 1
        assert "SDK_SCOPE_MARKER_617" not in two
        assert (await host.reload("extension-contract")).ok
        assert (await host.build_prompt(workspace_id="one")).count(
            "SDK_SCOPE_MARKER_617",
        ) == 1
        await host.unload("extension-contract")
        assert "SDK_SCOPE_MARKER_617" not in await host.build_prompt(
            workspace_id="one",
        )


async def test_timed_out_hook_that_ignores_cancellation_blocks_reload(
    tmp_path,
):
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.hooks import HookPhase
    from qwenpaw.plugins.messages import ContentBlock, Message
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
import asyncio
from pathlib import Path
from qwenpaw.plugins.hooks import HookPhase, HookResult, HookSpec
from qwenpaw.plugins.messages import ContentBlock, Message


class Plugin:
    def register(self, ctx):
        async def stubborn(call):
            directory = Path(ctx.config.get("directory"))
            while not (directory / "release").exists():
                try:
                    await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    (directory / "cancelled").touch()
            (directory / "finished").touch()
            return HookResult(
                replace_input=(
                    Message(
                        "user", (ContentBlock(text="too late"),)
                    ),
                )
            )

        ctx.register_hook(
            HookSpec(
                name="stubborn",
                phase=HookPhase.PRE_DISPATCH,
                handler=stubborn,
                timeout=0.03,
            )
        )


plugin = Plugin()
"""
    messages = (Message("user", (ContentBlock(text="original"),)),)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(tmp_path, source, ["hooks"]),
            config={"directory": str(tmp_path)},
        )
        try:
            result = await asyncio.wait_for(
                host.run_hooks(HookPhase.PRE_DISPATCH, messages=messages),
                WAIT_TIMEOUT,
            )
            assert result.action == "continue" and result.replace_input is None
            async with asyncio.timeout(WAIT_TIMEOUT):
                while True:
                    if (tmp_path / "cancelled").exists():
                        break
                    await asyncio.sleep(0.01)
            assert (tmp_path / "cancelled").exists()
            assert (
                host.resource_snapshot("extension-contract")["active_calls"]
                > 0
            )
            with pytest.raises(PluginBusyError):
                await host.reload("extension-contract")
        finally:
            (tmp_path / "release").touch()
            async with asyncio.timeout(WAIT_TIMEOUT):
                while True:
                    if (
                        host.resource_snapshot("extension-contract")[
                            "active_calls"
                        ]
                        == 0
                    ):
                        break
                    await asyncio.sleep(0.01)
        assert (tmp_path / "finished").exists()
        assert result.replace_input is None
        assert (await host.reload("extension-contract")).ok


async def test_late_hook_phase_cannot_replace_input(tmp_path, caplog):
    from qwenpaw.plugins.hooks import HookPhase
    from qwenpaw.plugins.messages import ContentBlock, Message
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.hooks import HookPhase, HookResult, HookSpec
from qwenpaw.plugins.messages import ContentBlock, Message


class Plugin:
    def register(self, ctx):
        async def rewrite(call):
            return HookResult(
                replace_input=(
                    Message(
                        "user", (ContentBlock(text="illegal"),)
                    ),
                )
            )

        ctx.register_hook(
            HookSpec(
                name="late-rewrite",
                phase=HookPhase.POST_RESPONSE,
                handler=rewrite,
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, source, ["hooks"]))
        result = await host.run_hooks(
            HookPhase.POST_RESPONSE,
            messages=(Message("user", (ContentBlock(text="original"),)),),
        )
        assert result.replace_input is None
        assert "replace" in caplog.text.lower()


@pytest.mark.parametrize(
    "case",
    ["invalid_action", "invalid_reply", "invalid_injection"],
)
async def test_invalid_hook_result_does_not_partially_mutate_runtime(
    tmp_path,
    caplog,
    case,
):
    from qwenpaw.plugins.messages import ContentBlock, Message
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.hooks import (
    HookPhase,
    HookResult,
    HookSpec,
    ContextInjection,
)
from qwenpaw.plugins.messages import ContentBlock, Message


class Plugin:
    def register(self, ctx):
        async def invalid(call):
            case = ctx.config.get("case")
            return HookResult(
                action=(
                    "bad" if case == "invalid_action" else "reply"
                ),
                message=Message(
                    "assistant",
                    (
                        ContentBlock(
                            type=(
                                "unsupported"
                                if case == "invalid_reply"
                                else "text"
                            ),
                            text="reply",
                        ),
                    ),
                ),
                replace_input=(
                    Message(
                        "user",
                        (ContentBlock(text="must not apply"),),
                    ),
                ),
                injections=(
                    ContextInjection(
                        "must not apply",
                        priority=(
                            "bad"
                            if case == "invalid_injection"
                            else 100
                        ),
                    ),
                ),
            )

        ctx.register_hook(
            HookSpec("invalid", HookPhase.PRE_DISPATCH, invalid)
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(tmp_path, source, ["hooks", "config"]),
            config={"case": case},
        )
        result = await host.run_hooks(
            "pre_dispatch",
            messages=(Message("user", (ContentBlock(text="original"),)),),
        )
        assert result.action == "continue"
        assert result.replace_input is None and result.injections == ()
        assert "SDKError" in caplog.text


@pytest.mark.parametrize(
    "phase, action",
    [
        ("post_agent_build", "reply"),
        ("post_response", "skip_agent"),
        ("on_error", "reply"),
        ("finally", "skip_agent"),
    ],
)
async def test_hook_control_flow_actions_rejected_where_runtime_ignores_them(
    tmp_path,
    caplog,
    phase,
    action,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.hooks import HookPhase, HookResult, HookSpec
from qwenpaw.plugins.messages import ContentBlock, Message


class Plugin:
    def register(self, ctx):
        async def control(call):
            return HookResult(
                action=ctx.config.get("action"),
                message=Message(
                    "assistant", (ContentBlock(text="reply"),)
                ),
            )

        ctx.register_hook(
            HookSpec(
                "control",
                HookPhase(ctx.config.get("phase")),
                control,
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(tmp_path, source, ["hooks", "config"]),
            config={"phase": phase, "action": action},
        )
        result = await host.run_hooks(phase)
        assert result.action == "continue" and result.message is None
        assert "Control-flow actions are not permitted" in caplog.text


async def test_released_hook_cannot_start_from_already_captured_dispatch_list(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
import asyncio
from pathlib import Path
from qwenpaw.plugins.hooks import HookSpec, HookPhase, HookResult
from qwenpaw.plugins.commands import CommandSpec, CommandResult


class Plugin:
    def register(self, ctx):
        async def first(call):
            directory = Path(ctx.config.get("directory"))
            (directory / "entered").touch()
            while not (directory / "release").exists():
                await asyncio.sleep(0.01)
            return HookResult()

        async def second(call):
            ctx.storage.write_json("revoked-hook-ran.json", True)
            return HookResult()

        ctx.register_hook(
            HookSpec(
                "first", HookPhase.PRE_EXECUTE, first, priority=10
            )
        )
        handle = ctx.register_hook(
            HookSpec(
                "second", HookPhase.PRE_EXECUTE, second, priority=20
            )
        )

        async def revoke(call, args):
            await handle.close()
            return CommandResult()

        ctx.register_command(CommandSpec("revokehook", revoke))


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(
                tmp_path,
                source,
                ["hooks", "commands", "storage", "config"],
            ),
            config={"directory": str(tmp_path)},
        )
        running = asyncio.create_task(host.run_hooks("pre_execute"))
        try:
            async with asyncio.timeout(WAIT_TIMEOUT):
                while True:
                    if (tmp_path / "entered").exists():
                        break
                    await asyncio.sleep(0.01)
            assert (tmp_path / "entered").exists()
            await host.call_command("/revokehook")
        finally:
            (tmp_path / "release").touch()
            await running
        assert ctx.storage.read_json("revoked-hook-ran.json", False) is False


@pytest.mark.parametrize("action", ["continue", "replace_input"])
async def test_command_result_controls_actual_runtime_model_input(
    tmp_path,
    action,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.commands import CommandSpec, CommandResult
from qwenpaw.plugins.messages import Message, ContentBlock
from qwenpaw.plugins.providers import (
    ProviderSpec,
    ModelInfo,
    ModelChunk,
)


class Plugin:
    def register(self, plugin):
        async def command(ctx, args):
            plugin.storage.write_json(
                "command.json",
                {
                    "args": args,
                    "count": plugin.storage.read_json(
                        "command.json", {}
                    ).get("count", 0)
                    + 1,
                },
            )
            return CommandResult(
                ACTION,
                messages=(
                    Message(
                        "user",
                        (ContentBlock(text="rewritten:" + args),),
                    ),
                ),
            )

        async def model(ctx, request):
            texts = [
                "".join(
                    b.text for b in m.content if b.type == "text"
                )
                for m in request.messages
                if m.role == "user"
            ]
            plugin.storage.write_json("model.json", texts)
            yield ModelChunk(
                (ContentBlock(text="model:" + texts[-1]),),
                is_last=True,
            )

        plugin.register_command(CommandSpec("commandflow", command))
        plugin.register_provider(
            ProviderSpec(
                "command-model",
                "Command model",
                model,
                models=(ModelInfo("model", "Model"),),
                require_api_key=False,
            )
        )


plugin = Plugin()
""".replace(
        "ACTION",
        repr(action),
    )
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(
                tmp_path,
                source,
                ["commands", "providers", "storage"],
            ),
        )
        await host.configure_chat_model("command-model", "model")
        events = [
            event async for event in host.stream_chat("/commandflow hello")
        ]
        expected = (
            "/commandflow hello" if action == "continue" else "rewritten:hello"
        )
        assert ctx.storage.read_json("command.json") == {
            "args": "hello",
            "count": 1,
        }
        assert ctx.storage.read_json("model.json") == [expected]
        assert any(
            block.text == "model:" + expected
            for event in events
            for block in event.content
        )


async def test_cancelled_sync_command_keeps_busy_until_actual_worker_finishes(
    tmp_path,
):
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
import time
from pathlib import Path
from qwenpaw.plugins.commands import CommandSpec, CommandResult
class Plugin:
    def register(self,plugin):
        def command(ctx,args):
            directory=Path(plugin.config.get('directory'))
            (directory/'entered').touch()
            try:
                while not (directory/'release').exists():
                    if ctx.cancelled: (directory/'cancel-observed').touch()
                    time.sleep(.01)
                return CommandResult()
            finally: (directory/'finished').touch()
        plugin.register_command(CommandSpec('syncwait',command))
plugin=Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(tmp_path, source, ["commands", "config"]),
            config={"directory": str(tmp_path)},
        )

        async def consume():
            return [event async for event in host.stream_chat("/syncwait")]

        invocation = asyncio.create_task(consume())
        try:
            async with asyncio.timeout(WAIT_TIMEOUT):
                while not (tmp_path / "entered").exists():
                    await asyncio.sleep(0.01)
            invocation.cancel()
            async with asyncio.timeout(WAIT_TIMEOUT):
                while not (tmp_path / "cancel-observed").exists():
                    await asyncio.sleep(0.01)
            invocation.cancel()
            assert not (tmp_path / "finished").exists()
            with pytest.raises(PluginBusyError):
                await host.reload("extension-contract")
            assert (
                host.resource_snapshot("extension-contract")["active_calls"]
                > 0
            )
        finally:
            (tmp_path / "release").touch()
            await asyncio.gather(invocation, return_exceptions=True)
        async with asyncio.timeout(WAIT_TIMEOUT):
            while not (tmp_path / "finished").exists():
                await asyncio.sleep(0.01)
        assert (await host.reload("extension-contract")).ok


@pytest.mark.parametrize("reply_source", ["command", "hook"])
async def test_public_reply_preserves_mixed_content_order_in_real_runtime(
    tmp_path,
    reply_source,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
import io
from PIL import Image
from qwenpaw.plugins.commands import CommandSpec, CommandResult
from qwenpaw.plugins.hooks import HookSpec, HookPhase, HookResult
from qwenpaw.plugins.messages import ContentBlock, Message


class Plugin:
    def register(self, plugin):
        def reply(ctx):
            plugin.storage.write_json(
                "reply-count.json",
                plugin.storage.read_json("reply-count.json", 0) + 1,
            )
            buffer = io.BytesIO()
            Image.new("RGB", (1, 1), "green").save(
                buffer, format="PNG"
            )
            image = ctx.media.write(
                "mixed.png",
                buffer.getvalue(),
                mime_type="image/png",
            )
            file = ctx.media.write(
                "mixed.txt",
                b"ordered attachment",
                mime_type="text/plain",
            )
            return Message(
                "assistant",
                (
                    ContentBlock(
                        text="before",
                        metadata={"author": "text"},
                        attributes={
                            "index": 99,
                            "object": "author-object",
                            "sdk_attributes": {"nested": True},
                        },
                    ),
                    ContentBlock("image", attachment=image),
                    ContentBlock(text="between"),
                    ContentBlock("file", attachment=file),
                    ContentBlock(text="after"),
                ),
                name="named-author",
                metadata={"author": "message"},
                attributes={
                    "custom_reply": "kept",
                    "sdk_message": {"author": True},
                },
            )

        async def command(ctx, args):
            return CommandResult("reply", reply(ctx))

        async def hook(ctx):
            return HookResult("reply", reply(ctx))

        REGISTER


plugin = Plugin()
""".replace(
        "REGISTER",
        (
            "plugin.register_command(CommandSpec('mixedreply',command))"
            if reply_source == "command"
            else (
                "plugin.register_hook(HookSpec('mixedreply',HookPhase"
                ".PRE_DISPATCH,hook))"
            )
        ),
    )
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(tmp_path, source, ["commands", "hooks", "storage"]),
        )
        events = [event async for event in host.stream_chat("/mixedreply")]
        completed = [
            event
            for event in events
            if event.object == "message" and event.status == "completed"
        ]
        assert len(completed) == 1
        blocks = completed[0].content
        assert [block.type for block in blocks] == [
            "text",
            "image",
            "text",
            "file",
            "text",
        ]
        assert [block.text for block in blocks if block.type == "text"] == [
            "before",
            "between",
            "after",
        ]
        assert blocks[1].attributes["image_url"]
        assert blocks[3].attributes["file_url"]
        assert ctx.storage.read_json("reply-count.json") == 1

        assert completed[0].attributes["name"] == "named-author"
        assert dict(completed[0].attributes["metadata"]) == {
            "author": "message",
        }
        identity = completed[0].attributes["sdk_message"]
        assert (
            identity["version"] == 1
            and identity["name"] == "named-author"
            and identity["role"] == "assistant"
        )
        assert identity["attributes"]["custom_reply"] == "kept"
        assert dict(identity["attributes"]["sdk_message"]) == {"author": True}
        assert blocks[0].index == 0 and blocks[0].object == "content"
        assert dict(blocks[0].attributes["metadata"]) == {"author": "text"}
        original = blocks[0].attributes["sdk_attributes"]
        assert (
            original["index"] == 99 and original["object"] == "author-object"
        )
        assert dict(original["sdk_attributes"]) == {"nested": True}
        # Public values are immutable mappings, but all retained author data is
        # JSON data and must survive an actual serialization round trip.
        import json
        from collections.abc import Mapping

        def plain(value):
            if isinstance(value, Mapping):
                return {key: plain(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [plain(item) for item in value]
            return value

        restored = json.loads(json.dumps(plain(identity)))
        assert restored["attributes"] == {
            "custom_reply": "kept",
            "sdk_message": {"author": True},
        }
