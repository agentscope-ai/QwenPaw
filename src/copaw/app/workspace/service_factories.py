# -*- coding: utf-8 -*-
"""Service factory functions for workspace components.

Factory functions are used by Workspace._register_services() to create
and initialize service components. Extracted from local functions to
improve testability and code organization.
"""

from typing import TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from .workspace import Workspace

logger = logging.getLogger(__name__)


async def create_mcp_service(ws: "Workspace", mcp):
    """Initialize MCP manager and attach to runner.

    Args:
        ws: Workspace instance
        mcp: MCPClientManager instance
    """
    # pylint: disable=protected-access
    if ws._config.mcp:
        try:
            await mcp.init_from_config(ws._config.mcp)
            logger.debug(f"MCP initialized for agent: {ws.agent_id}")
        except Exception as e:
            logger.warning(f"Failed to init MCP: {e}")
    ws._service_manager.services["runner"].set_mcp_manager(mcp)
    # pylint: enable=protected-access


async def create_chat_service(ws: "Workspace", service):
    """Create and attach chat manager, or reuse existing one.

    Args:
        ws: Workspace instance
        service: Existing ChatManager if reused, None if creating new
    """
    # pylint: disable=protected-access
    from ..runner.manager import ChatManager
    from ..runner.repo.json_repo import JsonChatRepository

    if service is not None:
        # Reused ChatManager - just wire to new runner
        cm = service
        logger.info(f"Reusing ChatManager for {ws.agent_id}")
    else:
        # Create new ChatManager
        chats_path = str(ws.workspace_dir / "chats.json")
        chat_repo = JsonChatRepository(chats_path)
        cm = ChatManager(repo=chat_repo)
        ws._service_manager.services["chat_manager"] = cm
        logger.info(f"ChatManager created: {chats_path}")

    # Always wire to new runner
    ws._service_manager.services["runner"].set_chat_manager(cm)
    # pylint: enable=protected-access


async def create_channel_service(ws: "Workspace", _):
    """Create channel manager if configured.

    Args:
        ws: Workspace instance
        _: Unused service parameter

    Returns:
        ChannelManager instance or None if not configured
    """
    # pylint: disable=protected-access
    if not ws._config.channels:
        return None

    from ...config import Config, update_last_dispatch
    from ..channels.manager import ChannelManager
    from ..channels.utils import make_process_from_runner

    temp_config = Config(channels=ws._config.channels)
    runner = ws._service_manager.services["runner"]

    def on_last_dispatch(channel, user_id, session_id):
        update_last_dispatch(
            channel=channel,
            user_id=user_id,
            session_id=session_id,
            agent_id=ws.agent_id,
        )

    cm = ChannelManager.from_config(
        process=make_process_from_runner(runner),
        config=temp_config,
        on_last_dispatch=on_last_dispatch,
        workspace_dir=ws.workspace_dir,
    )
    ws._service_manager.services["channel_manager"] = cm
    return cm
    # pylint: enable=protected-access


async def create_agent_config_watcher(ws: "Workspace", _):
    """Create agent config watcher if channel/cron exists.

    Args:
        ws: Workspace instance
        _: Unused service parameter

    Returns:
        AgentConfigWatcher instance or None if not needed
    """
    # pylint: disable=protected-access
    channel_mgr = ws._service_manager.services.get("channel_manager")
    cron_mgr = ws._service_manager.services.get("cron_manager")

    if not (channel_mgr or cron_mgr):
        return None

    from ..agent_config_watcher import AgentConfigWatcher

    watcher = AgentConfigWatcher(
        agent_id=ws.agent_id,
        workspace_dir=ws.workspace_dir,
        channel_manager=channel_mgr,
        cron_manager=cron_mgr,
    )
    ws._service_manager.services["agent_config_watcher"] = watcher
    return watcher
    # pylint: enable=protected-access


async def create_mcp_config_watcher(ws: "Workspace", _):
    """Create MCP config watcher if MCP manager exists.

    Args:
        ws: Workspace instance
        _: Unused service parameter

    Returns:
        MCPConfigWatcher instance or None if not needed
    """
    # pylint: disable=protected-access
    mcp_mgr = ws._service_manager.services.get("mcp_manager")
    if not mcp_mgr:
        return None

    from ..mcp.watcher import MCPConfigWatcher
    from ...config.config import load_agent_config

    def mcp_config_loader():
        agent_config = load_agent_config(ws.agent_id)
        return agent_config.mcp

    watcher = MCPConfigWatcher(
        mcp_manager=mcp_mgr,
        config_loader=mcp_config_loader,
        config_path=ws.workspace_dir / "agent.json",
    )
    ws._service_manager.services["mcp_config_watcher"] = watcher
    return watcher
    # pylint: enable=protected-access
