# -*- coding: utf-8 -*-
"""A2A list tool: list registered remote A2A agents for the current agent.

Reads the per-agent ``a2a_config.json`` and returns a summary of all
registered remote agents with their connection info and capabilities.
"""

import json
import logging

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

logger = logging.getLogger(__name__)


async def a2a_list() -> ToolResponse:
    """列出当前智能体已注册的远程 A2A Agent。

    无需参数。自动读取当前智能体的 A2A 配置，返回所有已注册的
    远程 Agent 信息（别名、URL、认证类型、连接状态、技能列表等）。

    Returns:
        ToolResponse: 包含已注册 Agent 列表的 JSON：
        - agents: Agent 列表，每个包含 alias, url, auth_type, name,
          description, skills, capabilities, status 等字段
    """
    from .a2a_config_helper import load_a2a_agents
    from modules.a2a.client_manager import get_a2a_manager

    agents_cfg = load_a2a_agents()
    manager = get_a2a_manager()

    agents_list = []
    for alias, reg in agents_cfg.items():
        url = reg.get("url", "")
        entry: dict = {
            "alias": alias,
            "url": url,
            "auth_type": reg.get("auth_type", ""),
        }
        card_info = await manager.get_card_info(url)
        if not card_info:
            try:
                card_info = await manager.connect(
                    agent_url=url,
                    auth_type=reg.get("auth_type", ""),
                    auth_token=reg.get("auth_token", ""),
                    gateway_config=reg.get("gateway_config"),
                )
            except Exception as exc:
                logger.debug("a2a_list: connect to %s failed: %s", url, exc)
                entry["status"] = "error"
                entry["error"] = str(exc)
                agents_list.append(entry)
                continue

        if card_info:
            entry["status"] = card_info.get("status", "connected")
            entry["name"] = card_info.get("name", "")
            entry["description"] = card_info.get("description", "")
            entry["skills"] = card_info.get("skills", [])
            entry["capabilities"] = card_info.get("capabilities", {})
        else:
            entry["status"] = "disconnected"

        agents_list.append(entry)

    result = json.dumps(
        {"agents": agents_list, "count": len(agents_list)},
        ensure_ascii=False,
        indent=2,
    )

    logger.info("a2a_list: found %d registered agents", len(agents_list))

    return ToolResponse(
        content=[TextBlock(type="text", text=result)],
    )
