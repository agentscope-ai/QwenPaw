# -*- coding: utf-8 -*-
"""Trusted request snapshots through public tools, commands and hooks."""

import asyncio
from dataclasses import FrozenInstanceError, asdict
import json

import pytest

from qwenpaw.plugins.commands import CommandResult, CommandSpec
from qwenpaw.plugins.messages import ContentBlock, Message
from qwenpaw.plugins.prompts import PromptSpec
from qwenpaw.plugins.tools import ToolResult, ToolSpec


async def test_concurrent_tool_and_command_identity(sdk_component):
    snapshots = []

    def declare(ctx):
        async def tool(call, args):
            before = call.identity
            await asyncio.sleep(0.01)
            assert call.identity is before
            snapshots.append(before)
            return ToolResult.text(json.dumps(asdict(before)))

        async def command(call, args):
            return CommandResult(
                "reply",
                Message(
                    "assistant",
                    (ContentBlock(text=json.dumps(asdict(call.identity))),),
                ),
            )

        ctx.register_tool(
            ToolSpec(
                "who",
                "identity",
                {"type": "object"},
                tool,
                enabled=True,
            ),
        )
        ctx.register_command(CommandSpec("who", command))

    async with sdk_component(declare, capabilities=("tools", "commands")) as (
        host,
        ctx,
    ):
        results = await asyncio.gather(
            *(
                host.call_tool(
                    "who",
                    {},
                    workspace_id=workspace,
                    session_id=session,
                    user_id=user,
                    channel=channel,
                )
                for workspace, session, user, channel in [
                    ("one", "shared", "alice", "console"),
                    ("one", "shared", "bob", "dingtalk"),
                    ("two", "other", "alice", "console"),
                ]
            ),
        )
        identities = [json.loads(result.content[0].text) for result in results]
        assert identities == [
            {
                "workspace_id": "one",
                "session_id": "shared",
                "user_id": "alice",
                "channel": "console",
            },
            {
                "workspace_id": "one",
                "session_id": "shared",
                "user_id": "bob",
                "channel": "dingtalk",
            },
            {
                "workspace_id": "two",
                "session_id": "other",
                "user_id": "alice",
                "channel": "console",
            },
        ]
        response = await host.call_command(
            "/who",
            workspace_id="one",
            session_id="shared",
            user_id="bob",
            channel="dingtalk",
        )
        assert json.loads(response.content[0].text) == identities[1]
        with pytest.raises(FrozenInstanceError):
            snapshots[0].user_id = "changed"


async def test_dynamic_prompt_uses_request_identity(sdk_component):
    def declare(ctx):
        ctx.register_prompt(
            PromptSpec(
                "dynamic",
                render=lambda identity: (
                    f"{identity.workspace_id}:{identity.session_id}:"
                    f"{identity.user_id}:{identity.channel}"
                ),
            ),
        )

    async with sdk_component(declare, capabilities=("prompts",)) as (host, _):
        assert (
            await host.build_prompt(
                workspace_id="one",
                session_id="s",
                user_id="alice",
                channel="dingtalk",
            )
            == "one:s:alice:dingtalk"
        )
