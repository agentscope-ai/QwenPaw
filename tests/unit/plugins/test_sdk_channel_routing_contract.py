# -*- coding: utf-8 -*-
"""Public channel identities and callbacks through the real shared queue."""

import asyncio

import pytest

from qwenpaw.plugins.channels import ChannelMessage
from qwenpaw.plugins.messages import ContentBlock
from qwenpaw.plugins.testing import PluginTestHost

from .sdk_author_fixture import make_plugin

from .timing import WAIT_TIMEOUT

CHANNEL = "contract-routed-channel"
SOURCE = """
import asyncio
from qwenpaw.plugins.channels import ChannelSpec
from qwenpaw.plugins.providers import (
    ProviderSpec,
    ModelInfo,
    ModelChunk,
)
from qwenpaw.plugins.messages import ContentBlock


class Plugin:
    def register(self, plugin):
        callback_lock = asyncio.Lock()

        def append(key, value):
            rows = plugin.storage.read_json(key, [])
            plugin.storage.write_json(key, [*rows, value])

        def snapshot(ctx, event):
            return {
                "workspace": ctx.workspace_id,
                "phase": event.phase,
                "status": event.status,
                "run_id": event.run_id,
                "message_ids": list(event.message_ids),
                "user_id": event.user_id,
                "sender_id": event.sender_id,
                "acl_sender_id": event.acl_sender_id,
            }

        class Backend:
            async def start(self, ctx):
                pass

            async def stop(self, ctx):
                return True

            async def send(self, ctx, message):
                append(
                    "sent.json",
                    {
                        "target": message.target,
                        "text": "".join(
                            p.text for p in message.content
                        ),
                    },
                )

            async def on_run(self, ctx, event):
                fault = plugin.storage.read_json(
                    "callback-fault.json", ""
                )
                if fault == "gate":
                    async with callback_lock:
                        append("events.json", snapshot(ctx, event))
                        if event.phase == "start":
                            while not plugin.storage.read_json(
                                "callback-release.json", False
                            ):
                                try:
                                    await asyncio.sleep(0.01)
                                except asyncio.CancelledError:
                                    pass
                    return
                append("events.json", snapshot(ctx, event))
                if fault == "raise":
                    raise RuntimeError("callback-only failure")
                if fault == "cancel":
                    raise asyncio.CancelledError()

        async def generate(ctx, request):
            messages = [
                "".join(
                    b.text for b in msg.content if b.type == "text"
                )
                for msg in request.messages
                if msg.role == "user"
            ]
            text = messages[-1]
            append(
                "model.json",
                {
                    "workspace": ctx.workspace_id,
                    "session": ctx.session_id,
                    "text": text,
                    "last_types": [
                        b.type
                        for b in [
                            m
                            for m in request.messages
                            if m.role == "user"
                        ][-1].content
                    ],
                },
            )
            try:
                if "hold-first" in text:
                    while not plugin.storage.read_json(
                        "release.json", False
                    ):
                        await asyncio.sleep(0.01)
                if text == "fail-before-content":
                    raise RuntimeError(
                        "model failure before any output"
                    )
                yield ModelChunk(
                    (
                        ()
                        if text == "empty-output"
                        else (ContentBlock(text="reply:" + text),)
                    ),
                    is_last=True,
                )
            finally:
                append("model-finished.json", text)

        plugin.register_channel(
            ChannelSpec(
                "contract-routed-channel",
                "Routing contract",
                Backend,
            )
        )
        plugin.register_provider(
            ProviderSpec(
                "routing-provider",
                "Routing model",
                generate,
                models=(
                    ModelInfo("routing-model", "Routing model"),
                ),
                require_api_key=False,
            )
        )


plugin = Plugin()
"""


async def wait_for(predicate):
    async with asyncio.timeout(WAIT_TIMEOUT):
        while not predicate():
            await asyncio.sleep(0.01)


async def setup(host, tmp_path, **settings):
    ctx = await host.load(
        make_plugin(tmp_path, SOURCE, ["channels", "providers", "storage"]),
    )
    await host.configure_chat_model("routing-provider", "routing-model")
    await host.start_channel(CHANNEL, settings)
    return ctx


def incoming(
    text,
    identifier,
    *,
    sender="allowed-name",
    acl="allowed-id",
    scope="group",
):
    return ChannelMessage(
        sender,
        (ContentBlock(text=text),),
        session_id="same-session",
        reply_to="target:" + sender,
        is_group=scope == "group",
        mentioned=True,
        message_id=identifier,
        acl_sender_id=acl,
        session_scope=scope,
    )


@pytest.mark.parametrize("denied_first", [False, True])
async def test_shared_group_filters_each_sender_before_real_queue_batch(
    tmp_path,
    denied_first,
):
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await setup(host, tmp_path, access_control_group=True)
        await host.set_channel_access(CHANNEL, "allowed-id", allowed=True)
        await host.set_channel_access(CHANNEL, "denied-id", allowed=False)
        await host.receive_channel(CHANNEL, incoming("hold-first", "first"))
        await wait_for(
            lambda: len(ctx.storage.read_json("model.json", [])) == 1,
        )
        batch = [
            incoming("permitted-body", "allowed"),
            incoming(
                "FORBIDDEN-BODY",
                "denied",
                sender="blocked-name",
                acl="denied-id",
            ),
        ]
        if denied_first:
            batch.reverse()
        try:
            for message in batch:
                await host.receive_channel(CHANNEL, message)
            # Both arrivals are queued behind the real first Runtime call.
            await asyncio.sleep(0.03)
            assert len(ctx.storage.read_json("model.json", [])) == 1
        finally:
            ctx.storage.write_json("release.json", True)
        await wait_for(
            lambda: any(
                e["status"] == "rejected"
                for e in ctx.storage.read_json("events.json", [])
            ),
        )
        await wait_for(
            lambda: len(ctx.storage.read_json("model-finished.json", [])) == 2,
        )
        calls = ctx.storage.read_json("model.json")
        assert calls[1]["text"] == "permitted-body"
        assert all("FORBIDDEN-BODY" not in item["text"] for item in calls)
        events = ctx.storage.read_json("events.json")
        starts = [e for e in events if e["phase"] == "start"]
        assert [e["message_ids"] for e in starts] == [["first"], ["allowed"]]
        assert all(e["user_id"] == "group" for e in starts)
        rejected = [e for e in events if e["status"] == "rejected"]
        assert len(rejected) == 1 and rejected[0]["message_ids"] == ["denied"]
        assert rejected[0]["phase"] == "end"
        assert rejected[0]["sender_id"] == "blocked-name"
        assert rejected[0]["acl_sender_id"] == "denied-id"
        await host.stop_channel(CHANNEL)


async def test_sender_scope_separates_real_queues_with_same_session(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await setup(host, tmp_path)
        await host.receive_channel(
            CHANNEL,
            incoming("hold-first", "a", sender="alice", scope="sender"),
        )
        await wait_for(
            lambda: len(ctx.storage.read_json("model.json", [])) == 1,
        )
        try:
            await host.receive_channel(
                CHANNEL,
                incoming("bob-progress", "b", sender="bob", scope="sender"),
            )
            await wait_for(
                lambda: "bob-progress"
                in ctx.storage.read_json("model-finished.json", []),
            )
            assert ctx.storage.read_json("model-finished.json") == [
                "bob-progress",
            ]
        finally:
            ctx.storage.write_json("release.json", True)
        await wait_for(
            lambda: len(ctx.storage.read_json("model-finished.json", [])) == 2,
        )
        await host.stop_channel(CHANNEL)


@pytest.mark.parametrize(
    "message,status",
    [("empty-output", "completed"), ("fail-before-content", "failed")],
)
async def test_run_terminal_without_content(tmp_path, message, status):
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await setup(host, tmp_path)
        await host.receive_channel(CHANNEL, incoming(message, "one"))
        await wait_for(
            lambda: any(
                e["phase"] == "end"
                for e in ctx.storage.read_json("events.json", [])
            ),
        )
        events = ctx.storage.read_json("events.json")
        assert [(e["phase"], e["status"]) for e in events] == [
            ("start", "running"),
            ("end", status),
        ]
        assert events[0]["run_id"] == events[1]["run_id"]
        assert all(e["message_ids"] == ["one"] for e in events)
        await host.stop_channel(CHANNEL)


@pytest.mark.parametrize("fault", ["raise", "cancel"])
async def test_run_callback_fault_does_not_cancel_real_reply(tmp_path, fault):
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await setup(host, tmp_path)
        ctx.storage.write_json("callback-fault.json", fault)
        await host.receive_channel(CHANNEL, incoming("ordinary", "one"))
        await wait_for(lambda: bool(ctx.storage.read_json("sent.json", [])))
        assert ctx.storage.read_json("sent.json") == [
            {"target": "target:allowed-name", "text": "reply:ordinary"},
        ]
        await wait_for(
            lambda: len(ctx.storage.read_json("events.json", [])) == 2,
        )
        assert (
            ctx.storage.read_json("events.json")[-1]["status"] == "completed"
        )
        await host.stop_channel(CHANNEL)


async def test_late_start_callback_retains_exactly_one_terminal_notification(
    tmp_path,
):
    from qwenpaw.plugins import PluginBusyError

    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await setup(host, tmp_path)
        ctx.storage.write_json("callback-fault.json", "gate")
        await host.receive_channel(CHANNEL, incoming("ordinary", "one"))
        try:
            # The first callback outlives its real five-second budget. Business
            # output proceeds, but the live callback remains generation-owned.
            async with asyncio.timeout(WAIT_TIMEOUT):
                while not ctx.storage.read_json("model-finished.json", []):
                    await asyncio.sleep(0.01)
            assert ctx.storage.read_json("events.json")[0]["phase"] == "start"
            with pytest.raises(PluginBusyError):
                await host.reload("extension-contract")
            # The terminal callback also meets the same held author lock.
            await asyncio.sleep(5.1)
        finally:
            ctx.storage.write_json("callback-release.json", True)
        await wait_for(
            lambda: len(ctx.storage.read_json("events.json", [])) == 2,
        )
        events = ctx.storage.read_json("events.json")
        assert [(e["phase"], e["status"]) for e in events] == [
            ("start", "running"),
            ("end", "completed"),
        ]
        assert events[0]["run_id"] == events[1]["run_id"]
        await host.stop_channel(CHANNEL)


async def test_sender_image_buffer_does_not_leak_into_same_session_peer(
    tmp_path,
):
    from PIL import Image
    from qwenpaw.plugins.messages import Attachment

    image_path = tmp_path / "alice.png"
    Image.new("RGB", (1, 1), "blue").save(image_path)
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await setup(host, tmp_path)
        await host.receive_channel(
            CHANNEL,
            ChannelMessage(
                "alice",
                (
                    ContentBlock(
                        type="image",
                        attachment=Attachment(
                            image_path.as_uri(),
                            "image/png",
                        ),
                    ),
                ),
                session_id="same-session",
                reply_to="target:alice",
                message_id="alice-image",
                session_scope="sender",
            ),
        )
        await asyncio.sleep(0.05)
        assert ctx.storage.read_json("model.json", []) == []
        await host.receive_channel(
            CHANNEL,
            incoming("bob-text", "bob-text", sender="bob", scope="sender"),
        )
        await wait_for(
            lambda: len(ctx.storage.read_json("model-finished.json", [])) == 1,
        )
        await host.receive_channel(
            CHANNEL,
            incoming(
                "alice-text",
                "alice-text",
                sender="alice",
                scope="sender",
            ),
        )
        await wait_for(
            lambda: len(ctx.storage.read_json("model-finished.json", [])) == 2,
        )
        calls = ctx.storage.read_json("model.json")
        assert (
            calls[0]["text"] == "bob-text"
            and "image" not in calls[0]["last_types"]
        )
        assert (
            calls[1]["text"] == "alice-text"
            and calls[1]["last_types"].count("image") == 1
        )
        await wait_for(
            lambda: len(
                [
                    e
                    for e in ctx.storage.read_json("events.json", [])
                    if e["phase"] == "end"
                ],
            )
            == 2,
        )
        starts = [
            e
            for e in ctx.storage.read_json("events.json")
            if e["phase"] == "start"
        ]
        assert starts[0]["message_ids"] == ["bob-text"]
        assert starts[1]["message_ids"] == ["alice-image", "alice-text"]
        await host.stop_channel(CHANNEL)


async def test_channel_boolean_config_survives_registry_and_start(
    tmp_path,
):
    source = SOURCE.replace(
        "async def start(self, ctx):\n                pass",
        (
            "async def start(self, ctx):\n                "
            "plugin.storage.write_json('boolean.json',ctx.config."
            "get('feature_enabled'))"
        ),
    )
    source = source.replace(
        (
            "ChannelSpec(\n                "
            '"contract-routed-channel",\n                "Routing '
            'contract",\n                Backend,\n            )'
        ),
        (
            "ChannelSpec('contract-routed-channel','Routing "
            "contract',Backend,config_fields=({'name':'feature_en"
            "abled','type':'boolean','label':'Feature','default':"
            "False},))"
        ),
    )
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(
                tmp_path,
                source,
                ["channels", "providers", "storage"],
            ),
        )
        await host.start_channel(CHANNEL, {"feature_enabled": True})
        assert ctx.storage.read_json("boolean.json") is True
        await host.stop_channel(CHANNEL)
        await host.start_channel(CHANNEL, {"feature_enabled": False})
        assert ctx.storage.read_json("boolean.json") is False
        await host.stop_channel(CHANNEL)


async def test_same_session_senders_keep_stream_terminal_and_run_ids(
    tmp_path,
):
    source = SOURCE.replace(
        "            async def on_run(self, ctx, event):",
        """            async def on_stream(self,ctx,event):
                append('streams.json', {
                    'phase':event.phase, 'status':event.event.status,
                    'target':event.target, 'text':event.text,
                    'run_id':event.run_id})
            async def on_run(self, ctx, event):""",
    )
    source = source.replace(
        '                if "hold-first" in text:',
        (
            "                yield ModelChunk((ContentBlock(text="
            "'begin:'+text+';'),))\n                if "
            "'hold-first' in text:"
        ),
    )
    source = source.replace(
        (
            "ChannelSpec(\n                "
            '"contract-routed-channel",\n                "Routing '
            'contract",\n                Backend,\n            )'
        ),
        (
            "ChannelSpec('contract-routed-channel','Routing "
            "contract',Backend,streaming=True)"
        ),
    )
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(
                tmp_path,
                source,
                ["channels", "providers", "storage"],
            ),
        )
        await host.configure_chat_model("routing-provider", "routing-model")
        await host.start_channel(CHANNEL)
        await host.receive_channel(
            CHANNEL,
            incoming("hold-first", "alice", sender="alice", scope="sender"),
        )
        try:
            await wait_for(
                lambda: any(
                    e["phase"] == "delta"
                    for e in ctx.storage.read_json("streams.json", [])
                ),
            )
            await host.receive_channel(
                CHANNEL,
                incoming("bob", "bob", sender="bob", scope="sender"),
            )
            await wait_for(
                lambda: any(
                    e["phase"] == "end" and e["target"] == "target:bob"
                    for e in ctx.storage.read_json("streams.json", [])
                ),
            )
            assert not any(
                e["phase"] == "end" and e["target"] == "target:alice"
                for e in ctx.storage.read_json("streams.json", [])
            )
        finally:
            ctx.storage.write_json("release.json", True)
        await wait_for(
            lambda: len(
                [
                    e
                    for e in ctx.storage.read_json("events.json", [])
                    if e["phase"] == "end"
                ],
            )
            == 2,
        )
        events = ctx.storage.read_json("events.json")
        ids = {
            e["sender_id"]: e["run_id"]
            for e in events
            if e["phase"] == "start"
        }
        assert len(set(ids.values())) == 2
        streams = ctx.storage.read_json("streams.json")
        for sender in ("alice", "bob"):
            rows = [e for e in streams if e["target"] == "target:" + sender]
            assert {e["run_id"] for e in rows} == {ids[sender]}
            assert len([e for e in rows if e["phase"] == "start"]) == 1
            assert len([e for e in rows if e["phase"] == "end"]) == 1
            assert rows[-1]["status"] == "completed"
        await host.stop_channel(CHANNEL)


async def test_channel_stop_retains_provider_tail_and_other_run(
    tmp_path,
):
    from qwenpaw.plugins import SDKError, PluginBusyError

    source = SOURCE.replace(
        "import asyncio\n",
        "import asyncio\nfrom pathlib import Path\n",
        1,
    )
    start_index = source.index("        async def generate(")
    end_index = source.index("        plugin.register_channel", start_index)
    source = (
        source[:start_index]
        + """
        async def generate(ctx, request):
            text = "".join(
                b.text
                for m in request.messages
                if m.role == "user"
                for b in m.content
                if b.type == "text"
            )
            if text == "independent":
                yield ModelChunk(
                    (ContentBlock(text="independent completed"),),
                    is_last=True,
                )
                return
            try:
                yield ModelChunk(
                    (ContentBlock(text="owned content"),), is_last=True
                )
            finally:
                plugin.storage.write_json("tail-entered.json", True)
                while not (
                    Path(plugin.config.get("directory")) / "release-tail"
                ).exists():
                    try:
                        await asyncio.sleep(0.01)
                    except asyncio.CancelledError:
                        pass
                plugin.storage.write_json("tail-finished.json", True)
"""
        + source[end_index:]
    )
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(
                tmp_path,
                source,
                ["channels", "providers", "storage", "config"],
            ),
            config={"directory": str(tmp_path)},
        )
        await host.configure_chat_model("routing-provider", "routing-model")
        await host.start_channel(CHANNEL)
        await host.receive_channel(CHANNEL, incoming("owned", "one"))
        try:
            await wait_for(
                lambda: ctx.storage.read_json("tail-entered.json", False),
            )
            with pytest.raises(SDKError):
                await host.stop_channel(CHANNEL)
            assert ctx.storage.read_json("tail-finished.json", False) is False
            with pytest.raises(PluginBusyError):
                await host.reload("extension-contract")
            async with asyncio.timeout(WAIT_TIMEOUT):
                events = [
                    event
                    async for event in host.stream_chat(
                        "independent",
                        session_id="independent",
                    )
                ]
            assert any(
                block.text == "independent completed"
                for event in events
                for block in event.content
            )
            assert ctx.storage.read_json("tail-finished.json", False) is False
        finally:
            (tmp_path / "release-tail").touch()
        await wait_for(
            lambda: ctx.storage.read_json("tail-finished.json", False),
        )
        await host.stop_channel(CHANNEL)
        assert (await host.reload("extension-contract")).ok


@pytest.mark.parametrize("kind", ["text", "image", "file"])
async def test_streaming_channel_delivers_command_single_terminal_content(
    tmp_path,
    kind,
):
    source = """
import io
from collections.abc import Mapping
from PIL import Image


def plain(value):
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    return value


from qwenpaw.plugins.channels import ChannelSpec
from qwenpaw.plugins.commands import CommandSpec, CommandResult
from qwenpaw.plugins.messages import ContentBlock, Message


class Plugin:
    def register(self, plugin):
        class Backend:
            async def start(self, ctx):
                pass

            async def stop(self, ctx):
                return True

            async def send(self, ctx, message):
                plugin.storage.write_json(
                    "out.json",
                    {
                        "count": plugin.storage.read_json(
                            "out.json", {}
                        ).get("count", 0)
                        + 1,
                        "target": message.target,
                        "content": [
                            {
                                "type": b.type,
                                "text": b.text,
                                "attributes": plain(b.attributes),
                            }
                            for b in message.content
                        ],
                    },
                )

            async def on_stream(self, ctx, event):
                rows = plugin.storage.read_json(
                    "raw-stream.json", []
                )
                plugin.storage.write_json(
                    "raw-stream.json",
                    [
                        *rows,
                        {
                            "phase": event.phase,
                            "status": event.event.status,
                            "type": event.event.type,
                            "content": [
                                {
                                    "type": b.type,
                                    "text": b.text,
                                    "data": plain(b.data),
                                    "attributes": plain(
                                        b.attributes
                                    ),
                                }
                                for b in event.event.content
                            ],
                        },
                    ],
                )
                if event.phase == "end":
                    plugin.storage.write_json(
                        "out.json",
                        {
                            "count": plugin.storage.read_json(
                                "out.json", {}
                            ).get("count", 0)
                            + 1,
                            "target": event.target,
                            "content": [
                                {
                                    "type": b.type,
                                    "text": b.text,
                                    "attributes": plain(
                                        b.attributes
                                    ),
                                }
                                for b in event.event.content
                            ],
                        },
                    )

        async def command(ctx, args):
            if args == "text":
                block = ContentBlock(text="single terminal text")
            else:
                buffer = io.BytesIO()
                if args == "image":
                    Image.new("RGB", (1, 1), "red").save(
                        buffer, format="PNG"
                    )
                else:
                    buffer.write(b"file body")
                attachment = ctx.media.write(
                    "single."
                    + ("png" if args == "image" else "txt"),
                    buffer.getvalue(),
                    mime_type=(
                        "image/png"
                        if args == "image"
                        else "text/plain"
                    ),
                )
                block = ContentBlock(
                    type=args, attachment=attachment
                )
            plugin.storage.write_json(
                "command-count.json",
                plugin.storage.read_json("command-count.json", 0)
                + 1,
            )
            return CommandResult(
                "reply", Message("assistant", (block,))
            )

        plugin.register_command(
            CommandSpec("singleterminal", command)
        )
        plugin.register_channel(
            ChannelSpec(
                "contract-routed-channel",
                "Terminal content",
                Backend,
                streaming=True,
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(tmp_path, source, ["channels", "commands", "storage"]),
        )
        await host.start_channel(CHANNEL)
        await host.receive_channel(
            CHANNEL,
            incoming("/singleterminal " + kind, "one", scope="sender"),
        )
        await wait_for(lambda: bool(ctx.storage.read_json("out.json", None)))
        result = ctx.storage.read_json("out.json")
        assert ctx.storage.read_json("command-count.json") == 1
        assert result["count"] == 1
        assert (
            result["target"] == "target:allowed-name"
            and len(result["content"]) == 1
        )
        block = result["content"][0]
        assert block["type"] == kind
        if kind == "text":
            assert block["text"] == "single terminal text"
        else:
            assert block["attributes"][kind + "_url"]
        await host.stop_channel(CHANNEL)


@pytest.mark.parametrize("timeout_then_retry", [False, True])
async def test_stop_preserves_entered_terminal_callback_and_transport(
    tmp_path,
    timeout_then_retry,
):
    from qwenpaw.plugins import PluginBusyError, SDKError

    source = """
import asyncio
from qwenpaw.plugins.channels import ChannelSpec
from qwenpaw.plugins.providers import (
    ProviderSpec,
    ModelInfo,
    ModelChunk,
)


class Plugin:
    def register(self, plugin):
        class Backend:
            async def start(self, ctx):
                pass

            async def stop(self, ctx):
                plugin.storage.write_json(
                    "transport-stopped.json", True
                )
                return True

            async def send(self, ctx, message):
                pass

            async def on_run(self, ctx, event):
                if event.phase != "end":
                    return
                plugin.storage.write_json(
                    "terminal-entered.json",
                    {
                        "status": event.status,
                        "run_id": event.run_id,
                    },
                )
                try:
                    while not plugin.storage.read_json(
                        "release-terminal.json", False
                    ):
                        await asyncio.sleep(0.01)
                    plugin.storage.write_json(
                        "terminal-delivered.json", True
                    )
                except asyncio.CancelledError:
                    plugin.storage.write_json(
                        "terminal-cancelled.json", True
                    )
                    raise
                finally:
                    plugin.storage.write_json(
                        "terminal-finished.json", True
                    )

        async def generate(ctx, request):
            yield ModelChunk((), is_last=True)

        plugin.register_channel(
            ChannelSpec(
                "contract-routed-channel",
                "Terminal custody",
                Backend,
            )
        )
        plugin.register_provider(
            ProviderSpec(
                "routing-provider",
                "Routing model",
                generate,
                models=(
                    ModelInfo("routing-model", "Routing model"),
                ),
                require_api_key=False,
            )
        )


plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(
                tmp_path,
                source,
                ["channels", "providers", "storage"],
            ),
        )
        await host.configure_chat_model("routing-provider", "routing-model")
        await host.start_channel(CHANNEL)
        await host.receive_channel(
            CHANNEL,
            incoming("empty-output", "terminal"),
        )
        await wait_for(lambda: ctx.storage.read_json("terminal-entered.json"))
        stopping = asyncio.create_task(host.stop_channel(CHANNEL))
        try:
            if timeout_then_retry:
                with pytest.raises(SDKError):
                    await asyncio.wait_for(
                        asyncio.shield(stopping),
                        WAIT_TIMEOUT,
                    )
                assert (
                    host.resource_snapshot("extension-contract")[
                        "active_calls"
                    ]
                    > 0
                )
                with pytest.raises(PluginBusyError):
                    await host.reload("extension-contract")
            else:
                await asyncio.sleep(0.05)
                assert (
                    not stopping.done()
                ), "Stop must await the accepted terminal callback"
            assert not ctx.storage.read_json("terminal-cancelled.json", False)
            assert not ctx.storage.read_json("terminal-finished.json", False)
            assert not ctx.storage.read_json("transport-stopped.json", False)
        finally:
            ctx.storage.write_json("release-terminal.json", True)
            results = await asyncio.gather(stopping, return_exceptions=True)
            if isinstance(results[0], BaseException):
                await host.stop_channel(CHANNEL)
        assert ctx.storage.read_json("terminal-delivered.json") is True
        assert ctx.storage.read_json("terminal-finished.json") is True
        assert ctx.storage.read_json("transport-stopped.json") is True
        assert not ctx.storage.read_json("terminal-cancelled.json", False)


@pytest.mark.parametrize("operation", ["stop", "reload", "unload"])
async def test_lifecycle_interrupt_delivers_cancelled_terminal_once(
    tmp_path,
    operation,
):
    import json

    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        ctx = await setup(host, tmp_path)
        await host.receive_channel(
            CHANNEL,
            incoming("hold-first", "interrupted"),
        )
        await wait_for(lambda: bool(ctx.storage.read_json("model.json", [])))
        before = ctx.storage.read_json("events.json")
        assert [(item["phase"], item["status"]) for item in before] == [
            ("start", "running"),
        ]
        if operation == "stop":
            await host.stop_channel(CHANNEL)
        elif operation == "reload":
            assert (
                await host.reload("extension-contract", interrupt_tasks=True)
            ).ok
        else:
            assert (
                await host.unload("extension-contract", interrupt_tasks=True)
            ).clean
        # Old contexts are correctly stale after replacement/unload. Read the
        # persisted callback evidence, not a newly fabricated callback context.
        data = root / "plugin-data/extension-contract"
        assert json.loads((data / "model-finished.json").read_text()) == [
            "hold-first",
        ]
        events = json.loads((data / "events.json").read_text())
        assert [(item["phase"], item["status"]) for item in events] == [
            ("start", "running"),
            ("end", "cancelled"),
        ]
        assert events[0]["run_id"] == events[1]["run_id"]
        assert events[1]["message_ids"] == ["interrupted"]


@pytest.mark.parametrize("operation", ["reload", "unload"])
async def test_lifecycle_terminal_callback_cannot_start_new_model_work(
    tmp_path,
    operation,
):
    import json

    source = SOURCE.replace(
        "from qwenpaw.plugins.messages import ContentBlock",
        (
            "from qwenpaw.plugins.messages import ContentBlock, "
            "Message\nfrom qwenpaw.plugins import SDKError, "
            "PluginBusyError"
        ),
    ).replace(
        '                if fault == "raise":',
        """                if event.phase=='end':
                    try:
                        await ctx.models.complete((Message(
                            'user', (
                                ContentBlock(text='forbidden-new-work'),
                            ),
                        ),))
                    except (SDKError, PluginBusyError):
                        append('new-work.json','rejected')
                    else:
                        append('new-work.json','accepted')
                if fault=='raise':""",
    )
    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        ctx = await host.load(
            make_plugin(
                tmp_path,
                source,
                ["channels", "providers", "storage"],
            ),
        )
        await host.configure_chat_model("routing-provider", "routing-model")
        await host.start_channel(CHANNEL, {})
        await host.receive_channel(
            CHANNEL,
            incoming("hold-first", "terminal-guard"),
        )
        await wait_for(lambda: bool(ctx.storage.read_json("model.json", [])))
        if operation == "reload":
            assert (
                await host.reload("extension-contract", interrupt_tasks=True)
            ).ok
        else:
            assert (
                await host.unload("extension-contract", interrupt_tasks=True)
            ).clean
        data = root / "plugin-data/extension-contract"
        events = json.loads((data / "events.json").read_text())
        assert [(event["phase"], event["status"]) for event in events] == [
            ("start", "running"),
            ("end", "cancelled"),
        ]
        assert json.loads((data / "new-work.json").read_text()) == ["rejected"]
        assert len(json.loads((data / "model.json").read_text())) == 1


async def test_interrupt_reload_retains_blocked_terminal_until_public_retry(
    tmp_path,
    monkeypatch,
    bounded_dependency_environment,
):
    from qwenpaw.app.channels.base import BaseChannel
    from qwenpaw.plugins import PluginBusyError

    owner_waiting = asyncio.Event()
    owner_release = asyncio.Event()
    retry_waiting = asyncio.Event()
    consume = BaseChannel._consume_with_tracker
    wait = asyncio.wait
    retry = None
    owner_task = None

    async def hold_owner(channel, request, payload):
        nonlocal owner_task
        owner_task = asyncio.current_task()
        try:
            await consume(channel, request, payload)
        finally:
            # Keep the real queue request alive until explicitly released.
            owner_waiting.set()
            await owner_release.wait()

    async def observe_wait(*args, **kwargs):
        if asyncio.current_task() is retry and owner_task in args[0]:
            retry_waiting.set()
        return await wait(*args, **kwargs)

    monkeypatch.setattr(BaseChannel, "_consume_with_tracker", hold_owner)
    monkeypatch.setattr(asyncio, "wait", observe_wait)

    source = SOURCE.replace(
        '                if fault == "raise":',
        """                if event.phase=='end':
                    plugin.storage.write_json('terminal-entered.json',True)
                    try:
                        while not plugin.storage.read_json(
                            'terminal-release.json', False,
                        ):
                            await asyncio.sleep(.01)
                    except asyncio.CancelledError:
                        plugin.storage.write_json(
                            'terminal-cancelled.json', True,
                        )
                        raise
                    plugin.storage.write_json('terminal-finished.json',True)
                if fault=='raise':""",
    )
    source = source.replace(
        "            async def stop(self, ctx):\n                return True",
        "            async def stop(self, ctx):\n"
        "                plugin.storage.write_json('transport-stopped.json', True)\n"
        "                return True",
    )
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(
                tmp_path,
                source,
                ["channels", "providers", "storage"],
            ),
        )
        await host.configure_chat_model("routing-provider", "routing-model")
        await host.start_channel(CHANNEL, {})
        try:
            await host.receive_channel(
                CHANNEL,
                incoming("hold-first", "terminal-wait"),
            )
            await wait_for(
                lambda: bool(ctx.storage.read_json("model.json", [])),
            )
            reload = asyncio.create_task(
                host.reload("extension-contract", interrupt_tasks=True),
            )
            try:
                await wait_for(
                    lambda: ctx.storage.read_json(
                        "terminal-entered.json",
                        False,
                    ),
                )
                with pytest.raises(PluginBusyError):
                    await reload
                assert not ctx.storage.read_json(
                    "terminal-cancelled.json",
                    False,
                )
                assert not ctx.storage.read_json(
                    "terminal-finished.json",
                    False,
                )
                assert (
                    host.resource_snapshot("extension-contract")[
                        "active_calls"
                    ]
                    > 0
                )
            finally:
                host.context("extension-contract").storage.write_json(
                    "terminal-release.json",
                    True,
                )
                await asyncio.wait_for(
                    asyncio.gather(reload, return_exceptions=True),
                    WAIT_TIMEOUT,
                )
            await asyncio.wait_for(owner_waiting.wait(), WAIT_TIMEOUT)
            await wait_for(
                lambda: ctx.storage.read_json("terminal-finished.json", False),
            )
            events = ctx.storage.read_json("events.json")
            assert [(event["phase"], event["status"]) for event in events] == [
                ("start", "running"),
                ("end", "cancelled"),
            ]
            assert events[0]["run_id"] == events[1]["run_id"]
            retry = asyncio.create_task(host.reload("extension-contract"))
            try:
                await wait_for(lambda: retry.done() or retry_waiting.is_set())
                if retry.done():
                    await retry  # Surface an unexpected Busy instead of a timeout.
                assert (
                    not retry.done()
                ), "Reload must wait for the real request"
                assert (
                    host.resource_snapshot("extension-contract")[
                        "active_calls"
                    ]
                    > 0
                )
                assert not ctx.storage.read_json(
                    "transport-stopped.json",
                    False,
                )
                assert not ctx.storage.read_json(
                    "terminal-cancelled.json",
                    False,
                )
            finally:
                owner_release.set()
                await asyncio.wait_for(
                    asyncio.gather(retry, return_exceptions=True),
                    WAIT_TIMEOUT,
                )
            assert (await retry).ok

        finally:
            owner_release.set()


@pytest.mark.parametrize("operation", ["stop", "reload", "unload"])
async def test_lifecycle_interrupt_closes_started_stream_once(
    tmp_path,
    operation,
):
    import json

    source = (
        SOURCE.replace(
            "            async def on_run(self, ctx, event):",
            """            async def on_stream(self, ctx, event):
                append('stream.json', {
                    'phase':event.phase, 'status':event.event.status,
                    'run_id':event.run_id,'text':event.text})
            async def on_run(self, ctx, event):""",
        )
        .replace(
            '                if "hold-first" in text:',
            """                yield ModelChunk(
                    (ContentBlock(text='visible-prefix'),), id='answer',
                )
                if 'hold-first' in text:""",
        )
        .replace(
            '"Routing contract",\n                Backend,\n            )',
            (
                '"Routing contract",\n                Backend, '
                "streaming=True,\n            )"
            ),
        )
    )
    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        ctx = await host.load(
            make_plugin(
                tmp_path,
                source,
                ["channels", "providers", "storage"],
            ),
        )
        await host.configure_chat_model("routing-provider", "routing-model")
        await host.start_channel(CHANNEL, {})
        await host.receive_channel(
            CHANNEL,
            incoming("hold-first", "stream-interrupt"),
        )
        await wait_for(
            lambda: any(
                row["phase"] == "delta"
                for row in ctx.storage.read_json("stream.json", [])
            ),
        )
        if operation == "stop":
            await host.stop_channel(CHANNEL)
        elif operation == "reload":
            assert (
                await host.reload("extension-contract", interrupt_tasks=True)
            ).ok
        else:
            assert (
                await host.unload("extension-contract", interrupt_tasks=True)
            ).clean
        data = root / "plugin-data/extension-contract"
        rows = json.loads((data / "stream.json").read_text())
        assert rows[0]["phase"] == "start"
        assert rows[-1]["phase"] == "end"
        assert [row["status"] for row in rows if row["phase"] == "end"] == [
            "cancelled",
        ]
        assert rows[-1]["text"] == "visible-prefix"
        events = json.loads((data / "events.json").read_text())
        assert [(event["phase"], event["status"]) for event in events] == [
            ("start", "running"),
            ("end", "cancelled"),
        ]
        assert {row["run_id"] for row in rows} == {events[0]["run_id"]}
