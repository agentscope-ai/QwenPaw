# -*- coding: utf-8 -*-
"""A2A discover tool: discover remote A2A Agent and get its info.

Resolves Agent Card, establishes authenticated connection,
and returns agent capabilities for the calling agent to decide
whether/how to interact with the remote agent.
"""

import json
import logging

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

logger = logging.getLogger(__name__)


async def a2a_discover(
    agent_url: str,
    auth_type: str = "",
    auth_token: str = "",
) -> ToolResponse:
    """发现远程 A2A Agent 并获取其信息。

    解析远程 Agent 的 Agent Card，获取其名称、描述、技能列表、
    支持的传输协议等信息。同时建立认证连接供后续 a2a_call 复用。

    Args:
        agent_url: 远程 A2A Agent 的基础 URL
                   (例: https://agent.example.com)
        auth_type: 认证类型，可选值:
                   - "bearer": Bearer Token 认证
                   - "api_key": API Key 认证
                   - "gateway": 智能网关（自动用 AK-SK 换取 Token）
                   - "": 无认证
        auth_token: 认证凭证（Bearer Token 或 API Key 值）
                    auth_type="gateway" 时无需传入

    Returns:
        ToolResponse: 包含 Agent Card 信息的 JSON：
        - name: Agent 名称
        - description: Agent 描述
        - skills: 技能列表（名称和描述）
        - interfaces: 支持的传输协议
        - capabilities: 是否支持流式/推送通知
        - status: 连接状态
    """
    from modules.a2a.client_manager import get_a2a_manager

    manager = get_a2a_manager()

    try:
        info = await manager.connect(
            agent_url=agent_url,
            auth_type=auth_type,
            auth_token=auth_token,
        )

        result = json.dumps(info, ensure_ascii=False, indent=2)
        logger.info(
            "a2a_discover success: %s (%s)",
            info.get("name"),
            agent_url,
        )

    except Exception as e:
        logger.error("a2a_discover failed for %s: %s", agent_url, e)
        result = json.dumps(
            {
                "url": agent_url,
                "status": "error",
                "error": str(e),
            },
            ensure_ascii=False,
        )

    return ToolResponse(
        content=[TextBlock(type="text", text=result)],
    )
