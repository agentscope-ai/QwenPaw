# -*- coding: utf-8 -*-
"""Mail F1 exploration mode activation tool."""
from __future__ import annotations

import logging

from agentscope.message import TextBlock
from agentscope.message import ToolResultState
from agentscope.tool import ToolChunk

from ...config.context import (
    activate_f1_for_session,
    get_current_session_id,
)
from ...runtime.tool_registry import tool_descriptor

logger = logging.getLogger(__name__)


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    policy_name="ActivateF1ExplorationMode",
    ui_description=(
        "Activate F1 exploration mode for step-by-step mail approval"
    ),
    ui_icon="🔍",
)
async def activate_f1_exploration_mode() -> ToolChunk:
    """Activate F1 exploration mode. Call this when an email cannot be
    classified by the triage tree (MAIL_TRIAGE.md) and you need to
    attempt handling it with per-tool user approval.

    After activation, work in two phases: first ANALYZE the email from
    the recipient's (user's) perspective — its intent and how the user
    would handle it — and output a brief plan; then ACT step by step,
    stating a one-sentence reason before each tool call. The SYSTEM
    automatically intercepts every tool call (mail read/write, file
    ops, browser use, shell, etc.) and shows your reason and action to
    the user for approval, for the remainder of this request.

    IMPORTANT: Do NOT ask the user for approval yourself in your chat
    output. Just call the tools you need as usual; approval is handled
    automatically by the system. If the user approves, the tool returns
    its normal result; if the user denies, the tool returns a denial
    message and you should retry with a different approach.

    Returns:
        `ToolChunk`: Confirmation that F1 mode is now active.
    """
    # The session_id ContextVar is set in PRE_DISPATCH (before the tool
    # coordinator spawns per-tool tasks), so it is readable here even
    # though this coroutine runs in its own asyncio task.
    session_id = get_current_session_id()
    if not session_id:
        logger.warning(
            "activate_f1_exploration_mode: no session_id in context; "
            "F1 mode NOT activated.",
        )
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "F1 探索模式激活失败：当前请求缺少 session_id，"
                        "无法登记逐步审批状态。请按最严格标准自行处理"
                        "（不确定的操作一律不要执行）。"
                    ),
                ),
            ],
        )
    activate_f1_for_session(session_id)
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[
            TextBlock(
                type="text",
                text=(
                    "F1 探索模式已激活。请按以下方式工作：\n"
                    "1. 先分析：代入收件人（用户）的身份通读这封邮件，"
                    "判断邮件意图、用户在这个场景下会怎么处理，"
                    "输出简短分析和处理计划。\n"
                    "2. 再行动：每次调用工具前，先用一句话说明理由"
                    "（例如“我想再仔细阅读一下这封邮件的细节”），"
                    "然后直接调用工具。\n"
                    "系统会自动拦截每个工具调用，"
                    "把你的理由和操作展示给用户审批：同意则执行；"
                    "拒绝则换一种思路。不要在对话中自行询问用户是否批准。"
                ),
            ),
        ],
    )
