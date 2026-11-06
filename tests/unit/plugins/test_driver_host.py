# -*- coding: utf-8 -*-
"""Host resource behavior is shared by every SDK Driver protocol."""

# pylint: disable=protected-access
from dataclasses import replace

from agentscope.message import TextBlock, ToolResultState

from qwenpaw.app.workspace.service_factories import create_driver_service
from qwenpaw.drivers.adapters.agentscope_tool import build_driver_agent_tools
from qwenpaw.drivers.contracts import DriverCard
from qwenpaw.plugins.testing import PluginTestHost

from .test_sdk_driver_lifecycle import card, driver_plugin, events


async def start_driver_service(workspace):
    def publish(service):
        workspace._service_manager.services["driver_manager"] = service

    return await create_driver_service(workspace, None, publish)


async def test_empty_workspace_keeps_driver_runtime_lazy(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        workspace = await host._workspace("test")
        runtime = await start_driver_service(workspace)
        try:
            assert await runtime.list_capabilities() == []
            assert await runtime.list_drivers() == []
            assert runtime.manager is None and runtime.watcher is None
        finally:
            await runtime.shutdown_all()


async def test_public_driver_is_callable_as_an_agentscope_tool(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        await host.open_driver(card())
        tools, _ = await build_driver_agent_tools(
            await host._driver_manager("test"),
            {
                "agent_id": "test",
                "session_id": "agent-query",
                "user_id": "alice",
            },
        )
        tool = next(item for item in tools if item.name == "same__echo")
        result = await tool(value="hello")
        assert result.state == ToolResultState.SUCCESS and result.is_last
        assert result.metadata["protocol"] == "public-sdk"
        assert any(
            isinstance(block, TextBlock) and block.text == "echo:echo"
            for block in result.content
        )


async def test_driver_configuration_and_plugin_shutdown_release_resources(
    tmp_path,
):
    async with PluginTestHost(tmp_path / "host") as host:
        context = await host.load(
            driver_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        workspace = await host._workspace("test")
        runtime = await start_driver_service(workspace)
        source = DriverCard(**card())
        try:
            await runtime.upsert_driver(source)
            assert any(
                row.name == "echo" for row in await runtime.list_capabilities()
            )
            assert len(events(context, "opened")) == 1
            await runtime.upsert_driver(replace(source, enabled=False))
            assert await runtime.list_capabilities() == []
            assert runtime.manager is None
            assert runtime.watcher is not None
            assert len(events(context, "closed")) == 1
            await runtime.upsert_driver(source)
            assert len(events(context, "opened")) == 2
            await host.unload("driver-lifecycle")
            assert runtime.manager is None and runtime.watcher is None
            assert len(events(context, "closed")) == 2
        finally:
            await runtime.shutdown_all()
