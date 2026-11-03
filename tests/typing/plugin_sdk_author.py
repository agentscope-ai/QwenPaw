# -*- coding: utf-8 -*-
"""Strict external-author typing: returned streams can always be closed."""

from pathlib import Path
from typing import AsyncGenerator, assert_type

from qwenpaw.plugins.apps import AppContext, ChatRequest, TaskSnapshot
from qwenpaw.plugins.events import ChatEvent
from qwenpaw.plugins.providers import ModelChunk
from qwenpaw.plugins.testing import PluginTestHost, TestModel
from qwenpaw.plugins.tools import ToolEvent, ToolContext


async def close_streams(
    app: AppContext,
    host: PluginTestHost,
    model: TestModel,
) -> None:
    chat = assert_type(
        app.chat_stream(ChatRequest("hello")),
        AsyncGenerator[ChatEvent, None],
    )
    task = assert_type(
        app.task_stream("owned-run"),
        AsyncGenerator[TaskSnapshot, None],
    )
    tool = assert_type(
        host.stream_tool("echo", {}),
        AsyncGenerator[ToolEvent, None],
    )
    host_chat = assert_type(
        host.stream_chat("hello"),
        AsyncGenerator[ChatEvent, None],
    )
    model_chat = assert_type(
        model.stream(()),
        AsyncGenerator[ModelChunk, None],
    )
    for stream in (chat, task, tool, host_chat, model_chat):
        await stream.aclose()


async def delegate_workspace(app: AppContext) -> None:
    from qwenpaw.plugins.apps import WorkspaceSummary

    workspaces = assert_type(
        await app.workspaces(),
        tuple[WorkspaceSummary, ...],
    )
    for workspace in workspaces:
        assert_type(workspace.id, str)
        assert_type(workspace.name, str)
        assert_type(workspace.enabled, bool)
        async with app.for_workspace(workspace.id) as scoped:
            assert_type(scoped, AppContext)
            assert_type(scoped.workspace_id, str)


async def channel_contract(host: PluginTestHost) -> None:
    from qwenpaw.plugins.channels import (
        ChannelHealth,
        ChannelMessage,
        ChannelRunEvent,
        ChannelStreamEvent,
        OutgoingMessage,
    )
    from qwenpaw.plugins.messages import ContentBlock

    incoming = ChannelMessage(
        "display-sender",
        (ContentBlock(text="hello"),),
        session_id="conversation",
        acl_sender_id="platform-sender",
        message_id="platform-message",
        session_scope="group",
        is_group=True,
    )
    assert_type(incoming.message_id, str)
    await host.receive_channel("example", incoming)
    await host.set_channel_access("example", "platform-sender", allowed=True)
    await host.send_channel(
        "example",
        "outgoing",
        user_id="user",
        session_id="session",
        require_delivery=True,
    )
    assert_type(await host.health_channel("example"), ChannelHealth)

    def correlate(  # pylint: disable=unused-variable
        event: ChannelRunEvent,
        streamed: ChannelStreamEvent,
        sent: OutgoingMessage,
    ) -> None:
        assert_type(event.message_ids, tuple[str, ...])
        assert_type(event.run_id, str)
        assert_type(streamed.run_id, str)
        assert_type(sent.run_id, str)
        assert_type(sent.require_delivery, bool)


async def context_services(call: "ToolContext") -> None:
    from qwenpaw.plugins.logging import PluginLogger
    from qwenpaw.plugins.models import ModelService
    from qwenpaw.plugins.messages import ContentBlock, Message
    from qwenpaw.plugins.providers import ModelToolChoice

    logger = assert_type(call.logger, PluginLogger)
    logger.info("author operation", fields={"stage": "begin", "count": 1})
    models = assert_type(call.models, ModelService)
    messages = (Message("user", (ContentBlock(text="question"),)),)
    result = assert_type(
        await models.complete(messages, options={"temperature": 0.2}),
        ModelChunk,
    )
    assert_type(result.is_last, bool)
    stream = assert_type(
        models.stream(
            messages,
            provider_id="example",
            model_id="example-model",
            tool_choice=ModelToolChoice("auto"),
            timeout=2.0,
        ),
        AsyncGenerator[ModelChunk, None],
    )
    await stream.aclose()


def custom_workspace_host(root: Path) -> PluginTestHost:
    return PluginTestHost(
        root,
        workspace_dirs={
            "sales": "sales/shared",
            "support": Path("support/shared"),
        },
    )


async def async_storage(call: ToolContext) -> None:
    from typing import Any
    from qwenpaw.plugins.messages import Attachment

    assert_type(await call.storage.aread_bytes("data.bin"), bytes)
    assert_type(await call.storage.aread_json("state.json", {}), Any)
    await call.storage.awrite_bytes("data.bin", b"data")
    await call.storage.awrite_json("state.json", {"count": 1})
    await call.storage.adelete("state.json")
    assert_type(await call.media.awrite("result.txt", b"result"), Attachment)
