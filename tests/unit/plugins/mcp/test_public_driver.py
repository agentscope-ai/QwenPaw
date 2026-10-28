# -*- coding: utf-8 -*-
# Test-only service/auth observations; plugin fixtures import public SDK only.
# pylint: disable=protected-access
"""Actual plugin through host discovery, governance, dispatch, and teardown."""

import asyncio
import json
from contextlib import suppress

import httpx
import pytest
from mcp.types import CallToolResult, Tool

from qwenpaw.plugins import SDKError
from qwenpaw.plugins.drivers import DriverCallResult
from qwenpaw.plugins.testing import PluginTestHost

from .fixtures import PLUGIN, PLUGIN_ID, Peer, card, mock_http, seed_card


async def test_manifest_registration_is_inert_and_sdk_only(tmp_path):
    manifest = json.loads((PLUGIN / "plugin.json").read_text())
    assert manifest["id"] == PLUGIN_ID
    assert manifest["sdk"]["version"] == "1.1.0"
    assert "drivers" in manifest["capabilities"]
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(PLUGIN)
        assert all(
            "driver_manager" not in workspace._service_manager.services
            for workspace in host._workspaces.values()
        )
        response = await host.request(
            "GET",
            "/api/qwenpaw-mcp/oauth/status/missing",
            user_id="alice",
        )
        assert response.status >= 400


@pytest.mark.parametrize("transport", ["stdio", "sse", "streamable_http"])
async def test_public_discover_invoke_and_close(
    tmp_path,
    monkeypatch,
    transport,
):
    peer = Peer()
    peer.install(monkeypatch)
    requests = []

    def endpoint(request):
        payload = json.loads(request.content)
        requests.append(payload)
        method = payload["method"]
        result = {
            "server/discover": {"supportedVersions": ["2026-07-28"]},
            "tools/list": {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo",
                        "inputSchema": {},
                    },
                ],
            },
            "tools/call": {"content": [{"type": "text", "text": "ok"}]},
        }[method]
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": result,
            },
        )

    mock_http(monkeypatch, endpoint)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(PLUGIN)
        assert not peer.opens and not requests
        await host.open_driver(card(transport=transport))
        rows = await host.list_driver_capabilities("same")
        assert len(rows) == 1
        assert rows[0]["name"] == "echo"
        assert (
            rows[0]["capability_id"] == "driver://mcp/same/tools/echo#invoke"
        )
        assert rows[0]["exposure"]["tool_name"] == "same__echo"
        assert rows[0]["enabled"] is True
        result = await host.call_driver("same", "echo", {"value": 42})
        assert isinstance(result, DriverCallResult)
        assert result.content[0].text == "ok"
        if transport == "streamable_http":
            call = next(r for r in requests if r["method"] == "tools/call")
            assert call["params"]["name"] == "echo"
            assert call["params"]["arguments"] == {"value": 42}
        else:
            assert peer.calls == [("echo", {"value": 42})]
        await host.close_driver("same")
        if transport != "streamable_http":
            assert peer.closes == [transport]
        await host.unload(PLUGIN_ID)
        host.assert_quiescent(PLUGIN_ID)


@pytest.mark.parametrize(
    "tools,enabled",
    [
        (None, True),
        ([], False),
        (["echo"], True),
        (["other"], False),
    ],
)
async def test_actual_whitelist_and_denied_policy(
    tmp_path,
    monkeypatch,
    tools,
    enabled,
):
    peer = Peer()
    peer.install(monkeypatch)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(PLUGIN)
        await host.open_driver(card(config={"tools": tools}))
        rows = await host.list_driver_capabilities("same")
        assert rows[0]["enabled"] is enabled
        if enabled:
            await host.call_driver("same", "echo", {})
            assert len(peer.calls) == 1
        else:
            with pytest.raises(SDKError):
                await host.call_driver("same", "echo", {})
            assert not peer.calls
        await host.open_driver(card(policy={"default_effect": "deny"}))
        before = len(peer.calls)
        with pytest.raises(SDKError, match="(?i)denied|permission|policy"):
            await host.call_driver("same", "echo", {})
        assert len(peer.calls) == before


@pytest.mark.parametrize("approved", [True, False])
async def test_actual_ask_gate_precedes_remote_invocation(
    tmp_path,
    monkeypatch,
    approved,
):
    peer = Peer()
    peer.install(monkeypatch)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(PLUGIN)
        await host.open_driver(card(policy={"default_effect": "ask"}))
        task = asyncio.create_task(
            host.call_driver(
                "same",
                "echo",
                {},
                session_id="approval",
                user_id="alice",
            ),
        )
        try:
            async with asyncio.timeout(3):
                while not (
                    pending := await host.approval_requests("approval")
                ):
                    await asyncio.sleep(0.005)
            assert not peer.calls and not task.done()
            assert await host.resolve_approval(
                pending[0].request_id,
                approved=approved,
            )
            if approved:
                assert isinstance(await task, DriverCallResult)
                assert peer.calls == [("echo", {})]
            else:
                with pytest.raises(SDKError):
                    await task
                assert not peer.calls
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task


async def test_names_ids_and_metadata_refresh_keep_connection(
    tmp_path,
    monkeypatch,
):
    peer = Peer()
    peer.tools = [
        Tool(name=name, description="Details", inputSchema={})
        for name in ["mcp__same__read", "pat.batch_plan", "-foo"]
    ]
    peer.install(monkeypatch)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(PLUGIN)
        await host.open_driver(
            card(
                config={
                    "display_name": "-MCP",
                    "tools": ["read"],
                },
            ),
        )
        rows = sorted(
            await host.list_driver_capabilities("same"),
            key=lambda r: ["read", "pat.batch_plan", "-foo"].index(r["name"]),
        )
        assert [r["name"] for r in rows] == ["read", "pat.batch_plan", "-foo"]
        assert [r["enabled"] for r in rows] == [True, False, False]
        assert [r["exposure"]["tool_name"] for r in rows] == [
            "tool_-MCP__read",
            "tool_-MCP__pat_batch_plan",
            "tool_-MCP__-foo",
        ]
        assert rows[1]["capability_id"] == (
            "driver://mcp/same/tools/pat.batch_plan#invoke"
        )
        assert "MCP server display name: -MCP." in rows[0]["description"]
        ids = [r["capability_id"] for r in rows]
        seed_card(
            tmp_path / "host",
            card(
                config={
                    "display_name": "New",
                    "tools": ["pat.batch_plan"],
                },
            ),
        )
        # Exercise the actual config-watcher refresh path; registering a
        # source through open_driver intentionally replaces its connection.
        manager = host._workspaces["test"]._service_manager.services[
            "driver_manager"
        ]
        await manager.refresh_driver("same")
        rows = sorted(
            await host.list_driver_capabilities("same"),
            key=lambda r: ["read", "pat.batch_plan", "-foo"].index(r["name"]),
        )
        assert [r["capability_id"] for r in rows] == ids
        assert [r["enabled"] for r in rows] == [False, True, False]
        assert rows[1]["exposure"]["tool_name"] == "New__pat_batch_plan"
        assert len(peer.opens) == 1 and not peer.closes
        await host.call_driver("same", "pat.batch_plan", {})
        assert peer.calls == [("pat.batch_plan", {})]


async def test_server_tool_inventory_refreshes_after_ttl_without_reconnect(
    tmp_path,
    monkeypatch,
):
    import time

    peer = Peer()
    peer.install(monkeypatch)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(PLUGIN)
        await host.open_driver(card())
        assert [
            r["name"] for r in await host.list_driver_capabilities("same")
        ] == ["echo"]
        peer.tools.append(Tool(name="new-tool", inputSchema={}))
        monotonic = time.monotonic
        with monkeypatch.context() as clock:
            clock.setattr(time, "monotonic", lambda: monotonic() + 11)
            rows = await host.list_driver_capabilities("same")
        assert [r["name"] for r in rows] == ["echo", "new-tool"]
        assert len(peer.opens) == 1 and not peer.closes
        await host.call_driver("same", "new-tool", {})
        assert peer.calls == [("new-tool", {})]


async def test_partial_open_cancel_closes_transport_in_its_owner_task(
    tmp_path,
    monkeypatch,
):
    peer = Peer()
    peer.initialize_gate = asyncio.Event()
    peer.install(monkeypatch)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(PLUGIN)
        task = asyncio.create_task(host.open_driver(card()))
        try:
            await asyncio.wait_for(peer.initialize_started.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            assert peer.closes == ["stdio"]
            assert not peer.calls
        finally:
            peer.initialize_gate.set()
            if not task.done():
                task.cancel()
            await asyncio.wait_for(
                asyncio.gather(task, return_exceptions=True),
                2,
            )


async def test_same_source_isolated_between_workspaces_and_unload_closes_both(
    tmp_path,
    monkeypatch,
):
    peer = Peer()
    peer.install(monkeypatch)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(PLUGIN)
        for workspace in ("one", "two"):
            await host.open_driver(card(), workspace_id=workspace)
        assert len(peer.opens) == 2
        await host.close_driver("same", workspace_id="one")
        assert len(peer.closes) == 1
        result = await host.call_driver("same", "echo", {}, workspace_id="two")
        assert result.content[0].text == "ok"
        await host.unload(PLUGIN_ID)
        assert len(peer.closes) == 2
        host.assert_quiescent(PLUGIN_ID)


@pytest.mark.parametrize("is_error", [False, True])
async def test_all_content_types_and_structured_result_cross_public_boundary(
    tmp_path,
    monkeypatch,
    is_error,
):
    from qwenpaw.plugins.messages import Attachment, ContentBlock

    peer = Peer()
    blocks = [
        {
            "type": "text",
            "text": "detail",
            "annotations": {"audience": ["user"]},
            "_meta": {"origin": "text"},
        },
        {"type": "image", "data": "aW1hZ2U=", "mimeType": "image/png"},
        {"type": "audio", "data": "YXVkaW8=", "mimeType": "audio/wav"},
        {
            "type": "resource",
            "resource": {
                "uri": "file:///synthetic.txt",
                "text": "embedded text",
                "mimeType": "text/plain",
            },
        },
        {
            "type": "resource",
            "resource": {
                "uri": "file:///synthetic.bin",
                "blob": "YmxvYg==",
                "mimeType": "application/octet-stream",
            },
        },
        {
            "type": "resource_link",
            "uri": "https://peer.invalid/document",
            "name": "document",
            "mimeType": "application/pdf",
            "size": 7,
        },
    ]
    peer.result = CallToolResult.model_validate(
        {
            "content": blocks,
            "structuredContent": {"nested": [1, {"ok": True}]},
            "isError": is_error,
            "_meta": {"trace": "synthetic"},
        },
    )
    peer.install(monkeypatch)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(PLUGIN)
        await host.open_driver(card())
        result = await host.call_driver("same", "echo", {})
        assert type(result) is DriverCallResult
        assert result.is_error is is_error
        assert result.structured_content == {"nested": (1, {"ok": True})}
        assert len(result.content) == 6
        assert all(type(b) is ContentBlock for b in result.content)
        assert result.content[0].text == "detail"
        assert result.content[0].metadata["mcp"]["annotations"][
            "audience"
        ] == ("user",)
        assert result.content[0].metadata["mcp"]["_meta"]["origin"] == "text"
        assert result.metadata["mcp"]["_meta"]["trace"] == "synthetic"
        assert [b.attachment.mime_type for b in result.content[1:]] == [
            "image/png",
            "audio/wav",
            "text/plain",
            "application/octet-stream",
            "application/pdf",
        ]
        assert all(
            type(b.attachment) is Attachment for b in result.content[1:]
        )
        assert (
            result.content[1].attachment.url
            == "data:image/png;base64,aW1hZ2U="
        )
        assert (
            result.content[2].attachment.url
            == "data:audio/wav;base64,YXVkaW8="
        )
        assert result.content[3].text == "embedded text"
        assert result.content[3].attachment.url == "file:///synthetic.txt"
        assert (
            result.content[4].attachment.url
            == "data:application/octet-stream;base64,YmxvYg=="
        )
        assert (
            result.content[5].attachment.url == "https://peer.invalid/document"
        )
        assert result.content[5].metadata["mcp"]["size"] == 7

        # Continue through the production consumer, using actual AgentScope.
        from agentscope.message import TextBlock, DataBlock, ToolResultState
        from qwenpaw.drivers.adapters.agentscope_tool import (
            build_driver_agent_tools,
        )

        manager = host._workspaces["test"]._service_manager.services[
            "driver_manager"
        ]
        tools, _ = await build_driver_agent_tools(
            manager,
            {"agent_id": "test"},
        )
        chunk = await next(
            tool for tool in tools if tool.name == "same__echo"
        )()
        assert chunk.is_last is True
        assert chunk.state is (
            ToolResultState.ERROR if is_error else ToolResultState.SUCCESS
        )
        assert chunk.metadata["mcp"]["_meta"]["trace"] == "synthetic"
        text = [
            block.text
            for block in chunk.content
            if isinstance(block, TextBlock)
        ]
        assert "detail" in text
        assert "embedded text" in text
        assert json.loads(text[-1]) == {"nested": [1, {"ok": True}]}
        data = [
            block.model_dump(mode="json")
            for block in chunk.content
            if isinstance(block, DataBlock)
        ]
        serialized = json.dumps(data)
        for payload in (
            "aW1hZ2U=",
            "YXVkaW8=",
            "YmxvYg==",
            "https://peer.invalid/document",
            "file:///synthetic.txt",
        ):
            assert payload in serialized
        for mime in (
            "image/png",
            "audio/wav",
            "application/octet-stream",
            "application/pdf",
        ):
            assert mime in serialized


@pytest.mark.parametrize("payload", [[1, "two"], 7, "value", True])
async def test_modern_nonobject_structured_output_is_not_lost(
    tmp_path,
    monkeypatch,
    payload,
):
    def endpoint(request):
        data = json.loads(request.content)
        result = {
            "server/discover": {"supportedVersions": ["2026-07-28"]},
            "tools/list": {"tools": [{"name": "echo", "inputSchema": {}}]},
            "tools/call": {"content": [], "structuredContent": payload},
        }[data["method"]]
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": data["id"],
                "result": result,
            },
        )

    mock_http(monkeypatch, endpoint)
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(PLUGIN)
        await host.open_driver(card(transport="streamable_http"))
        result = await host.call_driver("same", "echo", {})
        assert result.structured_content == (
            tuple(payload) if isinstance(payload, list) else payload
        )


async def test_partial_open_failed_close_retains_retryable_transport_custody(
    tmp_path,
    monkeypatch,
):
    import sys

    clients = []
    allow_close = False
    loaded = True

    class Transport:
        def __init__(self, **_kwargs):
            self.is_connected = True
            self._lifecycle_task = object()
            self.live = True
            clients.append(self)

        async def connect(self, **_kwargs):
            raise ConnectionError("synthetic partial transport open")

        async def close(self, ignore_errors=True):
            if not allow_close:
                if not ignore_errors:
                    raise RuntimeError("synthetic transport close blocked")
                return
            self.live = False
            self.is_connected = False
            self._lifecycle_task = None

    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(PLUGIN)
        # Replace only the low-level transport endpoint, preserving the real
        # plugin connection, host registration, cleanup ownership and retry.
        connection = sys.modules["plugin_qwenpaw_mcp.connection"]
        monkeypatch.setattr(connection, "StdIOStatefulClient", Transport)
        try:
            with pytest.raises(SDKError):
                await host.open_driver(card())
            assert len(clients) == 1 and clients[0].live
            report = await host.unload(PLUGIN_ID)
            loaded = not report.quiescent
            assert not report.quiescent
            assert clients[0].live
            allow_close = True
            report = await host.unload(PLUGIN_ID)
            loaded = not report.quiescent
            assert report.quiescent
            assert not clients[0].live
        finally:
            allow_close = True
            if loaded:
                await host.unload(PLUGIN_ID)


async def test_stateful_reaper_retains_public_host_custody_until_exit(
    tmp_path,
    monkeypatch,
):
    import sys

    peer = Peer()
    peer.exit_gate = asyncio.Event()
    peer.install(monkeypatch)
    loaded = True
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(PLUGIN)
        transport = sys.modules["plugin_qwenpaw_mcp.mcp_stateful_client"]
        monkeypatch.setattr(transport, "_LIFECYCLE_JOIN_TIMEOUT", 0.01)
        try:
            await host.open_driver(card())
            with pytest.raises(SDKError):
                await asyncio.wait_for(host.close_driver("same"), 1)
            await asyncio.wait_for(peer.exit_started.wait(), 1)
            assert not peer.closes
            report = await asyncio.wait_for(host.unload(PLUGIN_ID), 1)
            loaded = not report.quiescent
            assert not report.quiescent
            assert transport._LIFECYCLE_REAPERS
            peer.exit_gate.set()
            async with asyncio.timeout(2):
                while transport._LIFECYCLE_REAPERS:
                    await asyncio.sleep(0.005)
            report = await host.unload(PLUGIN_ID)
            loaded = not report.quiescent
            assert report.quiescent
            assert peer.closes == ["stdio"]
            host.assert_quiescent(PLUGIN_ID)
        finally:
            peer.exit_gate.set()
            if loaded:
                await host.unload(PLUGIN_ID)


async def test_cancelled_rpc_retains_public_host_owner_until_rpc_finishes(
    tmp_path,
    monkeypatch,
):
    import sys

    peer = Peer()
    peer.rpc_gate = asyncio.Event()
    peer.install(monkeypatch)
    loaded = True
    caller = None
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(PLUGIN)
        transport = sys.modules["plugin_qwenpaw_mcp.mcp_stateful_client"]
        monkeypatch.setattr(transport, "_SESSION_RPC_DRAIN_TIMEOUT", 0.01)
        monkeypatch.setattr(transport, "_LIFECYCLE_JOIN_TIMEOUT", 0.03)
        try:
            await host.open_driver(card())
            caller = asyncio.create_task(host.call_driver("same", "echo", {}))
            await asyncio.wait_for(peer.rpc_started.wait(), 1)
            caller.cancel()
            # Normal request cancellation must stay bounded even if its
            # underlying thirdparty RPC suppresses cancellation indefinitely.
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(caller, 1)
            assert peer.rpc_tasks and not peer.rpc_tasks[0].done()
            close_returned = False
            try:
                await asyncio.wait_for(host.close_driver("same"), 1)
                close_returned = True
            except SDKError:
                pass
            report = await asyncio.wait_for(host.unload(PLUGIN_ID), 1)
            loaded = not report.quiescent
            assert not peer.rpc_tasks[0].done()
            assert not close_returned, "Strict close lost the unfinished RPC"
            assert not report.quiescent, "Unload lost the unfinished RPC owner"
            peer.rpc_gate.set()
            await asyncio.wait_for(asyncio.gather(*peer.rpc_tasks), 1)
            report = await asyncio.wait_for(host.unload(PLUGIN_ID), 1)
            loaded = not report.quiescent
            assert report.quiescent
            host.assert_quiescent(PLUGIN_ID)
        finally:
            peer.rpc_gate.set()
            if caller is not None and not caller.done():
                caller.cancel()
                await asyncio.wait_for(
                    asyncio.gather(caller, return_exceptions=True),
                    1,
                )
            await asyncio.wait_for(
                asyncio.gather(*peer.rpc_tasks, return_exceptions=True),
                1,
            )
            if loaded:
                await host.unload(PLUGIN_ID)
