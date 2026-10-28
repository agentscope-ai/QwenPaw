# -*- coding: utf-8 -*-
"""In-place source updates revoke awaited work without reconnecting."""

# Only test setup observes the actual workspace service; the fake protocol
# imports exclusively public SDK APIs and callbacks run through the host.
# pylint: disable=protected-access

import asyncio
import json
from contextlib import suppress

import pytest
from agentscope.message import DataBlock, TextBlock, ToolResultState

from qwenpaw.drivers.adapters.agentscope_tool import build_driver_agent_tools
from qwenpaw.drivers.contracts import DriverCard
from qwenpaw.plugins import SDKError
from qwenpaw.plugins.testing import PluginTestHost

from ..plugins.test_sdk_driver_lifecycle import (
    PLUGIN_ID,
    SOURCE,
    card,
    driver_plugin,
    events,
    seed_card,
    wait_until,
)


def manager_for(host):
    workspace = host._workspaces["test"]
    return workspace._service_manager.services["driver_manager"]


async def test_metadata_refresh_rejects_awaited_discovery_without_reconnecting(
    tmp_path,
):
    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        await host.open_driver(
            card(
                config={
                    "display_name": "Before",
                    "wait_discover": True,
                },
            ),
        )
        pending = asyncio.create_task(host.list_driver_capabilities("same"))
        try:
            await wait_until(lambda: events(context, "discover"))
            seed_card(
                root,
                "test",
                card(
                    config={
                        "display_name": "After",
                        "wait_discover": True,
                        "tools": ["echo"],
                    },
                ),
            )
            await manager_for(host).refresh_driver("same")
            assert len(events(context, "create")) == 1
            assert not events(context, "closed")
            (tmp_path / "release-discover").touch()
            with pytest.raises(SDKError, match="(?i)metadata|stale|changed"):
                await pending
            capabilities = await host.list_driver_capabilities("same")
            echo = next(row for row in capabilities if row["name"] == "echo")
            assert echo["exposure"]["tool_name"] == "After__echo"
            assert echo["enabled"] is True
            assert all(
                row["enabled"] is False
                for row in capabilities
                if row["name"] != "echo"
            )
            await host.call_driver("same", "echo", {})
            assert len(events(context, "create")) == 1
            assert not events(context, "closed")
        finally:
            (tmp_path / "release-discover").touch()
            if not pending.done():
                pending.cancel()
                with suppress(asyncio.CancelledError, SDKError):
                    await pending


async def test_policy_update_revokes_pending_approval_without_reconnecting(
    tmp_path,
):
    async with PluginTestHost(tmp_path / "host") as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        await host.open_driver(card(effect="ask"))
        pending = asyncio.create_task(
            host.call_driver(
                "same",
                "echo",
                {},
                session_id="changed-policy",
            ),
        )
        try:
            async with asyncio.timeout(3):
                while not (
                    requests := await host.approval_requests(
                        "changed-policy",
                    )
                ):
                    await asyncio.sleep(0.005)
            assert len(requests) == 1
            assert not events(context, "invoke")
            await manager_for(host).sync_driver_policy(
                DriverCard(**card(effect="deny")),
            )
            assert await host.resolve_approval(
                requests[0].request_id,
                approved=True,
            )
            with pytest.raises(SDKError, match="(?i)metadata|stale|changed"):
                await pending
            with pytest.raises(SDKError, match="(?i)denied|permission|policy"):
                await host.call_driver("same", "echo", {})
            assert not events(context, "invoke")
            await manager_for(host).sync_driver_policy(
                DriverCard(**card(effect="allow")),
            )
            await host.call_driver("same", "echo", {})
            assert len(events(context, "invoke")) == 1
            assert len(events(context, "create")) == 1
            assert not events(context, "closed")
        finally:
            if not pending.done():
                pending.cancel()
                with suppress(asyncio.CancelledError, SDKError):
                    await pending


@pytest.mark.parametrize("is_error", [False, True])
async def test_agentscope_adapter_converts_public_driver_result(
    tmp_path,
    is_error,
):
    async with PluginTestHost(tmp_path / "host") as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        await host.open_driver(card())
        tools, _ = await build_driver_agent_tools(
            manager_for(host),
            {
                "agent_id": "test",
                "session_id": "adapter-session",
                "user_id": "alice",
                "channel": "console",
            },
        )
        tool = next(item for item in tools if item.name == "same__echo")
        result = await tool(error=is_error, nested={"values": [1, 2]})
        assert result.state is (
            ToolResultState.ERROR if is_error else ToolResultState.SUCCESS
        )
        assert result.is_last is True
        assert result.metadata["protocol"] == "public-sdk"
        text = [
            block.text
            for block in result.content
            if isinstance(block, TextBlock)
        ]
        assert text[0] == "echo:echo"
        structured = json.loads(text[-1])
        assert structured["arguments"] == {
            "error": is_error,
            "nested": {"values": [1, 2]},
        }
        assert structured["session"] == "adapter-session"
        attachments = [
            block for block in result.content if isinstance(block, DataBlock)
        ]
        assert len(attachments) == 1
        assert str(attachments[0].source.url) == (
            "https://example.invalid/picture.png"
        )
        assert attachments[0].source.media_type == "image/png"
        assert attachments[0].name == "picture"
        assert len(events(context, "invoke")) == 1


async def test_retired_protocol_failed_close_preserves_new_protocol_owner(
    tmp_path,
):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    source_a, source_b = driver_plugin(first), driver_plugin(second)
    (source_b / "main.py").write_text(
        SOURCE.replace(
            "author-driver",
            "driver-b",
        ).replace("driver-manage", "driver-manage-b"),
    )
    manifest_path = source_b / "plugin.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["id"] = "driver-lifecycle-b"
    manifest_path.write_text(json.dumps(manifest))
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(source_a, config={"directory": str(tmp_path)})
        context_b = await host.load(
            source_b,
            config={"directory": str(tmp_path)},
        )
        await host.open_driver(card(config={"fail_close": True}))
        try:
            with pytest.raises(SDKError, match="(?i)close|cleanup"):
                await host.open_driver(card(protocol="driver-b"))
            assert len(events(context_b, "opened")) == 1
            assert not events(context_b, "closed")
            before = await host.call_driver("same", "echo", {})
            assert before.content[0].text == "echo:echo"
            await asyncio.wait_for(host.unload(PLUGIN_ID), 5)
            assert not events(context_b, "closed")
            after = await host.call_driver("same", "echo", {})
            assert after.content[0].text == "echo:echo"
            assert len(events(context_b, "invoke")) == 2
        finally:
            (tmp_path / "allow-close").touch()
