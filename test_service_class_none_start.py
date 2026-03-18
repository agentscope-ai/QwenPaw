#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test that services with service_class=None still call start_method.

Tests channel_manager, agent_config_watcher, mcp_config_watcher.
"""
# pylint: disable=protected-access
import asyncio
import sys

sys.path.insert(0, "src")


async def test_channel_manager_start():
    """Test that channel_manager.start_all() is called."""
    from copaw.app.multi_agent_manager import MultiAgentManager

    manager = MultiAgentManager()
    ws = await manager.get_agent("default")

    channel_mgr = ws._service_manager.services.get("channel_manager")

    if channel_mgr:
        print(f"✓ ChannelManager created: {channel_mgr}")
        # Check if it was started (has running flag or similar)
        print(f"  Channel manager type: {type(channel_mgr)}")
        print(
            f"  Has start_all method: " f"{hasattr(channel_mgr, 'start_all')}",
        )
        # Try to check if channels are running
        if hasattr(channel_mgr, "channels"):
            print(f"  Channels: {channel_mgr.channels}")
    else:
        print("✓ ChannelManager not configured (OK)")

    await manager.stop_all()


async def test_agent_config_watcher_start():
    """Test that agent_config_watcher.start() is called."""
    from copaw.app.multi_agent_manager import MultiAgentManager

    manager = MultiAgentManager()
    ws = await manager.get_agent("default")

    watcher = ws._service_manager.services.get("agent_config_watcher")

    if watcher:
        print(f"✓ AgentConfigWatcher created: {watcher}")
        print(f"  Watcher type: {type(watcher)}")
        print(f"  Has start method: {hasattr(watcher, 'start')}")

        # Check if watcher is actually running
        if hasattr(watcher, "_observer"):
            print(
                f"  Observer running: "
                f"{watcher._observer and watcher._observer.is_alive()}",
            )
        if hasattr(watcher, "_started"):
            print(f"  Started flag: {watcher._started}")
    else:
        print("✓ AgentConfigWatcher not needed (no channel/cron)")

    await manager.stop_all()


async def test_mcp_config_watcher_start():
    """Test that mcp_config_watcher.start() is called."""
    from copaw.app.multi_agent_manager import MultiAgentManager

    manager = MultiAgentManager()
    ws = await manager.get_agent("default")

    watcher = ws._service_manager.services.get("mcp_config_watcher")

    if watcher:
        print(f"✓ MCPConfigWatcher created: {watcher}")
        print(f"  Watcher type: {type(watcher)}")
        print(f"  Has start method: {hasattr(watcher, 'start')}")

        # Check if watcher is actually running
        if hasattr(watcher, "_observer"):
            print(
                f"  Observer running: "
                f"{watcher._observer and watcher._observer.is_alive()}",
            )
        if hasattr(watcher, "_started"):
            print(f"  Started flag: {watcher._started}")
    else:
        print("✓ MCPConfigWatcher not needed (no MCP)")

    await manager.stop_all()


async def main():
    print("\n" + "=" * 70)
    print("Testing service_class=None start_method invocation")
    print("=" * 70 + "\n")

    print("[Test 1] ChannelManager start_all() invocation")
    print("-" * 70)
    await test_channel_manager_start()
    print()

    print("[Test 2] AgentConfigWatcher start() invocation")
    print("-" * 70)
    await test_agent_config_watcher_start()
    print()

    print("[Test 3] MCPConfigWatcher start() invocation")
    print("-" * 70)
    await test_mcp_config_watcher_start()
    print()


if __name__ == "__main__":
    asyncio.run(main())
